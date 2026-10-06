# -*- coding: utf-8 -*-
"""Reglages communs aux tests.

Le cache des sondes de compilateurs (Toolchains._SondeConnue) est COUPE par
defaut pendant les tests : plusieurs d'entre eux simulent une sonde qui echoue
sur un compilateur reellement installe, et un succes memorise d'un vrai build
le leur cacherait. tests/test_sondes_cache.py le rallume, sur un fichier a lui.
"""
import os

os.environ.setdefault("JENGA_SONDES_SANS_CACHE", "1")
