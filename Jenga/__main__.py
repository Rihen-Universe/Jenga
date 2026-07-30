#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Point d'entree `python -m Jenga`.

Permet d'invoquer la CLI sans script d'entree installe ni `pip install` :

    python -m Jenga build --config Debug

C'est ce dont a besoin un hote qui EMBARQUE Jenga (NKCode : shim
`tools/jenga.cmd` appelant le Python embarque) pour offrir un `jenga` en ligne
de commande aux commandes qui exigent un vrai terminal — `jenga gdb`, session
interactive — sur une machine ou Python n'est pas installe.

Sans ce fichier, `python -m Jenga` echoue avec « 'Jenga' is a package and cannot
be directly executed ».
"""

import sys

from .Jenga import main

if __name__ == "__main__":
    sys.exit(main())
