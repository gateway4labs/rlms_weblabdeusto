WebLab-Deusto plug-in
=====================

The `LabManager <http://github.com/lms4labs/labmanager/>`_ provides an API for
supporting more Remote Laboratory Management Systems (RLMS). This project is the
implementation for the `WebLab-Deusto <http://www.weblab.deusto.es/>`_ RLMS.

Usage
-----

First install the module::

  $ pip install git+https://github.com/lms4labs/rlms_weblabdeusto.git

Then add it in the LabManager's ``config.py``::

  RLMS = ['weblabdeusto', ... ]

Profit!
