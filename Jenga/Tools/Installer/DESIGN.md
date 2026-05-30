# Jenga Installer — Conception

Système d'installateur **maison, self-extracting, multi-plateforme**, intégré à
Jenga. Aucune dépendance externe (ni WiX, ni Inno Setup, ni dpkg, ni pkgbuild).

> Édité par **Rihen** — fait partie de Jenga.

---

## 1. Principe

`jenga package --type jng` produit **un exécutable d'installation autonome** :

```
monapp-setup.exe   (Windows)
monapp-setup.run   (Linux,  ELF)
monapp-setup       (macOS, Mach-O)
```

Cet exécutable = **stub natif** (compilé par Jenga) + **payload** (manifeste +
archive des fichiers) accolé en fin de binaire. À l'exécution chez l'utilisateur
final, le stub s'auto-extrait et installe l'application.

---

## 2. Format du fichier installateur

```
+=====================================================================+
|  STUB  (binaire natif : .exe / ELF / Mach-O, compile par Jenga)     |
+=====================================================================+
|  PAYLOAD                                                            |
|    MANIFEST : texte UTF-8, format `cle=valeur` + sections `[xxx]`    |
|    (1 octet 0x00 separateur)                                        |
|    ARCHIVE : suite d'entrees, pour chaque fichier :                 |
|       path_len   : u32 LE                                           |
|       path       : path_len octets (UTF-8, separateur '/')          |
|       mode       : u32 LE  (permissions POSIX ; 0 => defaut)        |
|       size       : u64 LE                                           |
|       data       : size octets                                      |
+=====================================================================+
|  TRAILER  (taille fixe = 80 octets, tout a la fin du fichier)       |
|       magic            : 8 octets = "JNGINST1"                       |
|       manifest_offset  : u64 LE  (offset absolu dans le fichier)    |
|       manifest_size    : u64 LE                                     |
|       archive_offset   : u64 LE                                     |
|       archive_entries  : u64 LE  (nombre de fichiers)               |
|       payload_crc32    : u32 LE  (integrite rapide)                 |
|       reserved         : u32 (0)                                    |
|       payload_sha256   : 32 octets (anti-tampering, verifie         |
|                          avant extraction par le stub)              |
+=====================================================================+
```

Le stub lit les **80 derniers octets** (trailer), vérifie le magic, puis se
repositionne via les offsets pour lire le manifeste et l'archive. Format
volontairement **simple** (pas de ZIP, pas de JSON) pour un stub C autonome,
sans dépendance tierce.

---

## 3. Manifeste (exemple)

```ini
name=MonApp
version=1.0.0
publisher=Rihen
exe=MonApp.exe
default_dir_windows=%LOCALAPPDATA%\Programs\MonApp
default_dir_linux=~/.local/opt/MonApp
default_dir_macos=/Applications/MonApp
license=LICENSE.txt

[shortcuts]
# nom|cible(relatif a l'install)|emplacement(desktop|menu)
MonApp|MonApp.exe|menu
MonApp|MonApp.exe|desktop

[firewall]
# commandes generees par Core/FirewallSpec.py (netsh / socketfilterfw / ufw)
add=netsh advfirewall firewall add rule name="MonApp (Network)" dir=in ...
del=netsh advfirewall firewall delete rule name="MonApp (Network)"
```

---

## 4. Déroulé d'installation (stub)

1. Localiser son propre binaire (`GetModuleFileName` / `/proc/self/exe` /
   `_NSGetExecutablePath`).
2. Lire et valider le **trailer** (magic, CRC).
3. Parser le **manifeste**.
4. Résoudre le **dossier d'installation** (option `--dir`, sinon défaut du
   manifeste avec expansion des variables d'env).
5. **Extraire** l'archive vers le dossier d'installation (crée l'arborescence).
6. Créer les **raccourcis** (Phase 2) : `.lnk` (Windows), `.desktop` (Linux),
   alias (macOS).
7. Ajouter la **règle pare-feu** (Phase 2) : exécute la commande `add` du
   manifeste.
8. Écrire un **désinstalleur** : `uninstall` (liste des fichiers installés +
   commande firewall `del`) ; sur Windows, entrée "Programmes et fonctionnalités".

## 5. Déroulé de désinstallation

`<install_dir>/uninstall[.exe]` lit la liste des fichiers posés, retire la règle
pare-feu, supprime les fichiers + raccourcis + l'entrée registre, puis se
supprime lui-même.

---

## 6. Interface CLI (Phase 1)

```
monapp-setup [--dir <chemin>] [--silent] [--help]
  --dir     dossier d'installation (defaut : manifeste)
  --silent  pas d'interaction (CI / déploiement auto)
```

Phase ultérieure : interface graphique (Welcome / EULA / dossier / progression).

---

## 7. Arborescence du code

```
Jenga/Tools/Installer/
  DESIGN.md            # ce document
  __init__.py
  stub/
    installer.c        # stub multi-plateforme (#ifdef WIN/LINUX/MACOS)
  Builder.py           # construit le .jng : archive + manifeste + concat + compile le stub
```

`Jenga/Commands/Package.py` ajoute le type `jng` qui appelle `Builder.py`, en
réutilisant : `dependfiles()`, icônes, `licensefile()`, et **`Core/FirewallSpec.py`**
pour les commandes pare-feu.

---

## 8. Objectif : parité avec Inno Setup / WiX

Le système doit, à terme, être **aussi puissant qu'Inno Setup et WiX**.
Fonctionnalités cibles (parité) :

| Domaine | Fonctionnalité | WiX/Inno | Jenga Installer |
|---------|----------------|:--------:|:---------------:|
| Base | Extraction + dossier d'install | ✅ | Phase 1 |
| Base | Désinstalleur propre | ✅ | Phase 1 |
| UX | EULA / licence | ✅ | Phase 3 |
| UX | Choix du dossier, composants optionnels | ✅ | Phase 3 |
| UX | Interface graphique (wizard) | ✅ | Phase 3 |
| UX | Multi-langues | ✅ | Phase 4 |
| Système | Raccourcis (menu/bureau) | ✅ | Phase 2 |
| Système | Entrée « Programmes et fonctionnalités » (registre) | ✅ | Phase 2 |
| Système | Règles pare-feu (FirewallSpec) | ⚠️ ext. | Phase 2 |
| Système | Associations de fichiers, variables PATH | ✅ | Phase 4 |
| Système | Pré/post-install hooks | ✅ | Phase 3 |
| Maj | Détection version installée / upgrade / repair | ✅ | Phase 4 |
| Compression | LZMA/zstd du payload | ✅ | Phase 3 |
| Intégrité | Checksum + signature | ✅ | Phase 2 |

## 9. Sécurité & protection antivirus (NATIF)

Les installateurs self-extracting sont **fréquemment signalés à tort** par les
antivirus (heuristique « stub + données accolées »). Protection à 3 niveaux,
intégrée nativement :

1. **Intégrité du payload** (Phase 2) : en plus du CRC32, un **hash SHA-256** du
   payload est stocké dans le trailer. Le stub **vérifie le hash AVANT
   extraction** et refuse de s'exécuter si le binaire a été altéré (anti-
   tampering / anti-injection de code).
2. **Signature de code** (Phase 2/3) : le `Builder` signe l'installateur final
   via les outils natifs si un certificat est fourni :
   - Windows : `signtool` (Authenticode) — évite les alertes SmartScreen/AV.
   - macOS : `codesign` + notarisation (`notarytool`).
   - Linux : signature détachée GPG optionnelle.
3. **Bonnes pratiques anti-faux-positifs** (dès Phase 1) :
   - **Aucune obfuscation ni chiffrement** du payload (les AV détectent
     l'entropie élevée comme suspecte) — données en clair, lisibles.
   - **Pas d'auto-modification** du binaire à l'exécution.
   - Manifeste Windows **UAC `asInvoker`** par défaut (pas d'élévation inutile) ;
     élévation demandée explicitement seulement si nécessaire (firewall, install
     pour tous les utilisateurs).
   - **Métadonnées de version** (VERSIONINFO Windows : éditeur Rihen, version,
     description) embarquées dans le stub — un exe « identifié » est moins suspect.
   - Le stub écrit dans des **emplacements utilisateur** par défaut (pas de
     `System32`, pas de comportement de type malware).

> Note : aucun installateur (même WiX/Inno) n'est « immunisé » contre les
> antivirus sans **signature de code**. La signature (niveau 2) est le levier
> décisif ; les niveaux 1 et 3 garantissent l'intégrité et minimisent les
> faux positifs.

## 10. Phasage

- **Phase 1 (MVP, fait)** : format + stub (extraction + dossier d'install +
  uninstaller) + Builder + CLI/silencieux. Bonnes pratiques anti-faux-positifs.
- **Phase 2 (fait)** : intégrité SHA-256 + raccourcis (.lnk + .desktop) + entrée
  désinstallation OS (registre Windows) + pare-feu (FirewallSpec) + intégration
  `jenga package --type jng` + **VERSIONINFO + manifeste UAC `asInvoker`**
  (anti-faux-positifs AV) + **signature Authenticode/codesign/GPG** si certificat
  fourni via le DSL (`signingcertificate`, `signingidentity`, `signinggpgkey`…).
- **Phase 3** : interface graphique (wizard EULA/dossier/composants/progression)
  + compression LZMA/zstd + hooks pré/post-install.
- **Phase 4** : multi-langues + associations de fichiers/PATH + upgrade/repair.
