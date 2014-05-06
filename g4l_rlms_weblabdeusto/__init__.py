# -*-*- encoding: utf-8 -*-*-

import sys
import json

from flask import request, Blueprint
from flask.ext.wtf import TextField, PasswordField, Required, URL, ValidationError

from labmanager.forms import AddForm, RetrospectiveForm, GenericPermissionForm
from labmanager.rlms import register, Laboratory, BaseRLMS, BaseFormCreator, register_blueprint, Capabilities, Versions
from labmanager import app

from .weblabdeusto_client import WebLabDeustoClient
from .weblabdeusto_data import ExperimentId

def get_module(version):
    """get_module(version) -> proper module for that version

    Right now, a single version is supported, so this module itself will be returned.
    When compatibility is required, we may change this and import different modules.
    """
    # TODO: check version
    return sys.modules[__name__]

class WebLabDeustoAddForm(AddForm):

    remote_login = TextField("Login",        validators = [Required()])
    password     = PasswordField("Password")

    base_url     = TextField("Base URL",    validators = [Required(), URL() ])

    mappings     = TextField("Mappings",     validators = [Required()], default = "{}")

    def __init__(self, add_or_edit, *args, **kwargs):
        super(WebLabDeustoAddForm, self).__init__(*args, **kwargs)
        self.add_or_edit = add_or_edit

    @staticmethod
    def process_configuration(old_configuration, new_configuration):
        old_configuration_dict = json.loads(old_configuration)
        new_configuration_dict = json.loads(new_configuration)
        if new_configuration_dict.get('password', '') == '':
            new_configuration_dict['password'] = old_configuration_dict.get('password','')
        return json.dumps(new_configuration_dict)

    def validate_password(form, field):
        if form.add_or_edit and field.data == '':
            raise ValidationError("This field is required.")

    def validate_mappings(form, field):
        try:
            content = json.loads(field.data)
        except:
            raise ValidationError("Invalid json content")
        
        if not isinstance(content, dict):
            raise ValidationError("Dictionary expected")
        
        for key in content:
            if not isinstance(key, basestring):
                raise ValidationError("Keys must be strings")
           
            if '@' not in key:
                raise ValidationError("Key format: experiment_name@experiment_category ")
                
            value = content[key]
            if not isinstance(value, basestring):
                raise ValidationError("Values must be strings")
           
            if '@' not in value:
                raise ValidationError("Value format: experiment_name@experiment_category ")

class WebLabDeustoPermissionForm(RetrospectiveForm):
    priority = TextField("Priority")
    time     = TextField("Time (in seconds)")

    def validate_number(form, field):
        if field.data != '' and field.data is not None:
            try:
                int(field.data)
            except:
                raise ValidationError("Invalid value. Must be an integer.")


    validate_priority = validate_number
    validate_time     = validate_number

class WebLabDeustoLmsPermissionForm(WebLabDeustoPermissionForm, GenericPermissionForm):
    pass

class WebLabFormCreator(BaseFormCreator):

    def get_add_form(self):
        return WebLabDeustoAddForm

    def get_permission_form(self):
        return WebLabDeustoPermissionForm

    def get_lms_permission_form(self):
        return WebLabDeustoLmsPermissionForm

FORM_CREATOR = WebLabFormCreator()

class RLMS(BaseRLMS):

    def __init__(self, configuration):
        """RLMS(configuration) -> instance of BaseRLMS
        
        'configuration' is always a JSON-encoded dictionary. 
        WebLab-Deusto expects to find three arguments:
        - remote_login
        - password
        - base_url

        A valid example of this would be:
        rlms = RLMS('{ "remote_login" : "weblabfed", "password" : "password", "base_url" : "https://www.weblab.deusto.es/weblab/" }')
        """
        self.configuration = configuration

        config = json.loads(configuration or '{}')
        self.login    = config.get('remote_login')
        self.password = config.get('password')
        self.base_url = config.get('base_url')
        
        if self.login is None or self.password is None or self.base_url is None:
            raise Exception("Laboratory misconfigured: fields missing" )

    def get_version(self):
        return Versions.VERSION_1

    def get_capabilities(self): 
        return [ Capabilities.WIDGET ] 

    def test(self):
        json.loads(self.configuration)
        # TODO
        return None

    def get_laboratories(self):
        client = WebLabDeustoClient(self.base_url)
        session_id = client.login(self.login, self.password)
        experiments = client.list_experiments(session_id)
        laboratories = []
        for experiment in experiments:
            id = '%s@%s' % (experiment['experiment']['name'], experiment['experiment']['category']['name'])
            laboratories.append(Laboratory(id, id))
        return laboratories

    def reserve(self, laboratory_id, username, institution, general_configuration_str, particular_configurations, request_payload, user_properties, *args, **kwargs):
        client = WebLabDeustoClient(self.base_url)
        session_id = client.login(self.login, self.password)

        consumer_data = {
            "user_agent"    : user_properties['user_agent'],
            "referer"       : user_properties['referer'],
            "from_ip"       : user_properties['from_ip'],
            "external_user" : '%s_%s' % (username, institution),
            #     "priority"      : "...", # the lower, the better
            #     "time_allowed"  : 100,   # seconds
            #     "initialization_in_accounting" :  False,
        }

        best_config = self._retrieve_best_configuration(general_configuration_str, particular_configurations)

        consumer_data.update(best_config)

        consumer_data_str = json.dumps(consumer_data)

        initial_data = request_payload.get('initial', '{}') or '{}'

        if 'back' in kwargs:
            back = kwargs['back']
        else:
            back = request.referrer

        reservation_status = client.reserve_experiment(session_id, ExperimentId.parse(laboratory_id), initial_data, consumer_data_str)
        return {
            'reservation_id' : reservation_status.reservation_id.id,
            'load_url' : "%sclient/federated.html#reservation_id=%s&back=%s" % (self.base_url, reservation_status.reservation_id.id, back)
        }

    def load_widget(self, reservation_id, widget_name, **kwargs):
        if 'back' in kwargs:
            back = kwargs['back']
        else:
            back = request.referrer
        return {
            'url' : "%sclient/federated.html#reservation_id=%s&widget=%s&back=%s" % (self.base_url, reservation_id, widget_name, back)
        }

    def list_widgets(self, laboratory_id):
        labs = app.config.get('WEBLABDEUSTO_LABS', {})
        default_widget = dict( name = 'default', description = 'Default widget')
        return labs.get(laboratory_id, [ default_widget ])

    def _retrieve_best_configuration(self, general_configuration_str, particular_configurations):
        max_time     = None
        min_priority = None

        for particular_configuration_str in particular_configurations:
            particular_configuration = json.loads(particular_configuration_str or '{}')
            if 'time' in particular_configuration:
                max_time = max(int(particular_configuration['time']), max_time)
            if 'priority' in particular_configuration:
                if min_priority is None:
                    min_priority = int(particular_configuration['priority'])
                else:
                    min_priority = min(int(particular_configuration['priority']), min_priority)

        MAX = 2 ** 30
        general_configuration = json.loads(general_configuration_str or '{}')
        if 'time' in general_configuration:
            global_max_time     = int(general_configuration['time'])
        else:
            global_max_time     = MAX
        if 'priority' in general_configuration:    
            global_min_priority = int(general_configuration['priority'])
        else:
            global_min_priority = None

        overall_max_time = min(global_max_time or MAX, max_time or MAX)
        if overall_max_time is MAX:
            overall_max_time = None

        overall_min_priority = max(global_min_priority, min_priority)

        consumer_data = {}
        if overall_min_priority is not None:
            consumer_data['priority'] = overall_min_priority
        if overall_max_time is not None:
            consumer_data['time_allowed'] = overall_max_time
        return consumer_data


weblabdeusto_blueprint = Blueprint('weblabdeusto', __name__)
@weblabdeusto_blueprint.route('/')
def index():
    return "This is the index for WebLab-Deusto"

register("WebLab-Deusto", ['4.0', '5.0'], __name__)
register_blueprint(weblabdeusto_blueprint, '/weblabdeusto')
