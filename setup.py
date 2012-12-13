from setuptools import setup

classifiers=[
    "Development Status :: 3 - Alpha",
    "Environment :: Web Environment",
    "Intended Audience :: Developers",
    "License :: Freely Distributable",
    "Operating System :: OS Independent",
    "Programming Language :: Python",
    "Programming Language :: Python :: 2",
    "Topic :: Internet :: WWW/HTTP",
    "Topic :: Software Development :: Libraries :: Application Frameworks",
]

cp_license="MIT"

# TODO: depend on lms4labs

setup(name='l4l_rlms_weblabdeusto',
      version='0.1',
      description="WebLab-Deusto plug-in in the lms4labs RLMS",
      classifiers=classifiers,
      author='WebLab-Deusto Team',
      author_email='weblab@deusto.es',
      url='http://github.com/lms4labs/rlms_weblabdeusto/',
      packages=['l4l_rlms_weblabdeusto'],
      license=cp_license,
     )
