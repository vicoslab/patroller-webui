#!/usr/bin/env python

from os.path import join, dirname, abspath, isfile
from distutils.core import setup
from setuptools import find_packages

this_directory = abspath(dirname(__file__))
with open(join(this_directory, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

install_requires = []
if isfile(join(this_directory, "requirements.txt")):
    with open(join(this_directory, "requirements.txt"), encoding='utf-8') as f:
        install_requires = f.readlines()

setup(name='patroller_webui',
    version='1.0',
    description='WebUI for patroller',
    long_description=long_description,
    long_description_content_type='text/markdown',
    author='Domen Tabernik',
    author_email='domen.tabernik@fri.uni-ljsi',
    url='https://github.com/vicoslab/patroller-webui',
    packages=find_packages(),
    install_requires=install_requires,
    include_package_data=True,
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: OS Independent",
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Science/Research",
    ],
    python_requires='>=3.6',
    entry_points={
        'console_scripts': ['patroller_webui=patroller_webui:main'],
    },
)