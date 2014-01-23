#!/usr/bin/env python

from distutils.core import setup

import sys

from __init__ import __version__
    
setup(name='pyfiscalprinter',
      version=__version__,
      description='Drivers for fiscal printers (Epson & Hasar) Argentina',
      author='Guillermo Narvaja',
      author_email='guillon@gmail.com',
      maintainer = "Mariano Reingart",
      maintainer_email = "reingart@gmail.com",
      url='http://code.google.com/p/pyfiscalprinter',
      packages=['pyfiscalprinter', ],
      package_dir={'pyfiscalprinter': "."},
      package_data={'pyfiscalprinter': []},
      classifiers = [
            "Development Status :: 5 - Production/Stable",
            "Intended Audience :: Developers",
            "License :: OSI Approved :: GNU Lesser General Public License v3 or later (LGPLv3+)",
            "Natural Language :: Spanish",
            "Programming Language :: Python",
            "Programming Language :: Python :: 2.5",
            "Programming Language :: Python :: 2.6",
            "Programming Language :: Python :: 2.7",
            "Operating System :: OS Independent",
            "Topic :: Office/Business :: Financial :: Point-Of-Sale",
            "Topic :: Software Development :: Libraries :: Python Modules",
            "Topic :: Printing",
      ],
      keywords="fiscal printer hasar epson",
     )

