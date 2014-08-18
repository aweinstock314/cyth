#!/usr/bin/env python2.7
from __future__ import absolute_import, division, print_function
from setuptools import setup
from utool import util_setup
import six


INSTALL_REQUIRES = [
    'Cython >= 0.20.2',
    'numpy >= 1.8.0',
    #'cv2',  # no pipi index
]

if six.PY2:
    INSTALL_REQUIRES += ['functools32 >= 3.2.3-1']

if __name__ == '__main__':
    kwargs = util_setup.setuptools_setup(
        setup_fpath=__file__,
        name='cyth',
        packages=util_setup.find_packages(),
        version=util_setup.parse_package_for_version('cyth'),
        license=util_setup.read_license('LICENSE'),
        long_description=util_setup.parse_readme('README.md'),
        ext_modules=util_setup.find_ext_modules(),
        cmdclass=util_setup.get_cmdclass(),
        description=('Cyth - convert python to cython'),
        url='https://github.com/aweinstock314/cyth',
        author='Avi Weinstock',
        author_email='aweinstock314@gmail.com',
        keywords='',
        install_requires=INSTALL_REQUIRES,
        scripts=['cyth/cyth_script.py', ],
        package_data={},
        classifiers=[],
    )
    setup(**kwargs)
