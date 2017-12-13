# -*-*- encoding: utf-8 -*-*-

import sys
import json
import datetime

from flask import request, Blueprint
from flask.ext.wtf import TextField, PasswordField, Required, URL, ValidationError

from labmanager.forms import AddForm, RetrospectiveForm, GenericPermissionForm
from labmanager.rlms import register, Laboratory, BaseRLMS, BaseFormCreator, register_blueprint, Capabilities, Versions
from labmanager import app

from .weblabdeusto_client import WebLabDeustoClient
from .weblabdeusto_data import ExperimentId

class WebLabDeustoAddForm(AddForm):

    DEFAULT_URL      = 'http://www.weblab.deusto.es/'
    DEFAULT_LOCATION = 'Bilbao, Spain'

    remote_login = TextField("Login",        validators = [Required()])
    password     = PasswordField("Password")

    base_url     = TextField("Base URL",    validators = [Required(), URL(False) ])

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
        return [ Capabilities.WIDGET, Capabilities.TRANSLATIONS, Capabilities.CHECK_URLS ]

    def test(self):
        try:
            self.get_laboratories()
        except Exception as e:
            return ["Invalid configuration or server is down: %s" % e]

    def get_laboratories(self):
        laboratories = WEBLAB_DEUSTO.rlms_cache.get('get_laboratories')
        if laboratories:
            return laboratories

        client = WebLabDeustoClient(self.base_url)
        session_id = client.login(self.login, self.password)
        experiments = client.list_experiments(session_id)
        laboratories = []
        for experiment in experiments:
            id = '%s@%s' % (experiment['experiment']['name'], experiment['experiment']['category']['name'])
            laboratories.append(Laboratory(id, id))

        WEBLAB_DEUSTO.rlms_cache['get_laboratories'] = laboratories
        return laboratories

    def get_check_urls(self, laboratory_id):
        return [ self.base_url ]

    def get_translations(self, laboratory_id):
        translations = WEBLAB_DEUSTO.rlms_cache.get(laboratory_id)
        if translations:
            return translations

        experiment_name, category_name = laboratory_id.split('@')
        translation_url = self.base_url
        if translation_url.endswith('/'):
            translation_url += 'web/i18n/'
        else:
            translation_url += '/web/i18n/'
        translation_url += category_name + '/' + experiment_name + '/'
        translations_r = WEBLAB_DEUSTO.cached_session.get(translation_url)
        if translations_r.status_code == 404:
            translations = { 'translations' : {}, 'mails' : {} }
        else:
            translations = translations_r.json()
        WEBLAB_DEUSTO.rlms_cache[laboratory_id] = translations
        return translations

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
        for key in 'group_name', 'group_id', 'user_fullname', 'user_username':
            if key in user_properties:
                consumer_data[key] = user_properties[key]

        if 'locale' in kwargs:
            consumer_data['locale'] = kwargs['locale']
            locale_string = "&locale=%s" % kwargs['locale']
        else:
            locale_string = ""

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
            'load_url' : "{}federated/?reservation_id={}&back_url={}{}".format(self.base_url, reservation_status.reservation_id.id, back, locale_string)
        }

    def load_widget(self, reservation_id, widget_name, **kwargs):
        if 'back' in kwargs:
            back = kwargs['back']
        else:
            back = request.referrer

        if 'locale' in kwargs:
            locale_string = "&locale=%s" % kwargs['locale']
        else:
            locale_string = ""

        return {
            'url' : "{}federated/?reservation_id={}&widget={}&back_url={}{}".format(self.base_url, reservation_id, widget_name, back, locale_string)
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


def populate_cache(rlms):
    for laboratory in rlms.get_laboratories():
        rlms.get_translations(laboratory.laboratory_id)

WEBLAB_DEUSTO = register("WebLab-Deusto", ['5.0'], __name__)
WEBLAB_DEUSTO.add_local_periodic_task('Populating cache', populate_cache, minutes = 55)


weblabdeusto_blueprint = Blueprint('weblabdeusto', __name__)
@weblabdeusto_blueprint.route('/')
def index():
    return "This is the index for WebLab-Deusto"

register_blueprint(weblabdeusto_blueprint, '/weblabdeusto')
