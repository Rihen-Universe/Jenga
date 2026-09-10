# Signature des applications (Windows, macOS, Linux)

Depuis Jenga **2.8.0**. Android et iOS avaient leur signature ; le bureau non,
et cela avait un coût mesurable.

---

## Pourquoi

Une signature ne rend pas un programme sûr. Elle répond à une question plus
modeste et plus utile : **qui l'a produit, et le fichier a-t-il changé depuis ?**

C'est ce que les systèmes d'exploitation demandent, et c'est ce que son absence
fait échouer. Un exécutable Windows non signé s'affiche « Éditeur inconnu », et
les moteurs heuristiques de Defender comptent l'absence de signature comme un
facteur aggravant. Quand le programme installe en plus une chaîne de
compilation, qui écrit des exécutables et lance des processus, la mise en
quarantaine devient probable. C'est arrivé, et c'est ce qui a motivé cette
fonctionnalité.

---

## Les trois systèmes ne font pas la même chose

C'est le point à comprendre avant tout le reste.

| Système | Où va la signature | Ce que vérifie le système |
|---|---|---|
| **Windows** | **dans** le fichier (Authenticode, en-tête PE) | à chaque lancement |
| **macOS** | **dans** le fichier (codesign) **+ notarisation** | Gatekeeper, à la première ouverture |
| **Linux** | **nulle part** dans le binaire | rien, au lancement |

**Linux n'a aucun équivalent d'Authenticode pour un ELF.** Le noyau ne vérifie
pas de signature. La convention du monde Linux est ailleurs, et elle est très
établie : on publie des **signatures détachées GPG** (`fichier.asc`) et des
**sommes de contrôle** (`SHA256SUMS`) à côté du téléchargement, et l'utilisateur
vérifie avant d'installer. Les paquets `.deb` et `.rpm` ont leur propre
signature, portée par le gestionnaire de paquets.

Prétendre que les trois font la même chose serait plus simple à documenter, et
faux.

---

## Déclarer la signature dans le `.jenga`

```python
with project("MonApp"):
    windowedapp()
    appurl("https://rihen-universe.com")

    with filter("system:Windows"):
        windowssign()
        windowscertificate("certs/rihen.pfx")     # ou le nom du sujet

    with filter("system:macOS"):
        macossign()
        macossigningidentity("Developer ID Application: Rihen (XXXXXXXXXX)")
        macosnotaryprofile("rihen")

    with filter("system:Linux"):
        linuxsign()
        linuxgpgkey("rihen.universe@gmail.com")
```

### Les mots de passe ne vont PAS dans le fichier de projet

Un secret dans un `.jenga` finit dans git, puis sur GitHub. Jenga lit d'abord
les variables d'environnement :

| Variable | Ce qu'elle porte |
|---|---|
| `JENGA_WINDOWS_CERT_PASSWORD` | mot de passe du `.pfx` |
| `JENGA_GPG_PASSPHRASE` | phrase secrète de la clé GPG |

`windowscertificatepass()` existe, et son emploi affiche un avertissement.
Aucun secret n'est journalisé : les commandes sont affichées avec la valeur
remplacée par `***`.

---

## Signer depuis la ligne de commande

Une release contient l'exécutable **et** son installeur : on veut les deux
signés, d'où `--file` répétable.

```bash
# Windows
jenga sign --platform windows --file dist/MonApp.exe --file dist/MonApp-setup.exe \
           --certificate certs/rihen.pfx

# macOS (signature puis notarisation de l'archive)
jenga sign --platform macos --file dist/MonApp.app --file dist/MonApp.zip \
           --identity "Developer ID Application: Rihen (XXXXXXXXXX)" \
           --notary-profile rihen

# Linux (signatures détachées + SHA256SUMS)
jenga sign --platform linux --file dist/MonApp-1.0-linux-x86_64.tar.gz \
           --gpg-key rihen.universe@gmail.com
```

Les options de la ligne de commande l'emportent sur ce que déclare le projet.
`--project MonApp` reprend la configuration du `.jenga` ; sans espace de
travail, la commande fonctionne quand même, ce qui est le cas d'un CI qui signe
une release déjà construite.

**Jenga refuse de signer si un fichier de la liste est absent.** Une release à
moitié signée est pire qu'une release non signée : personne ne va la vérifier
fichier par fichier.

---

## Les outils, et comment Jenga les trouve

| Système | Outil natif | Équivalent portable |
|---|---|---|
| Windows | `signtool` (SDK Windows) | `osslsigncode` (tourne aussi sous Linux et macOS) |
| macOS | `codesign` (outils Xcode) | `rcodesign` |
| Linux | `gpg` | — |

`signtool` n'est presque jamais dans le `PATH` : il est rangé par version de
SDK, dans un sous-dossier par architecture. Jenga prend la plus récente.

`osslsigncode` mérite d'être connu : c'est lui qui permet de signer un binaire
Windows **depuis un CI Linux**, ce que fait la moitié du monde.

---

## Trois pièges qui coûtent cher

**L'horodatage n'est pas optionnel.** Sans `/tr`, la signature cesse d'être
valable à l'expiration du certificat, et **tous les binaires déjà distribués**
deviennent « non fiables ». C'est la différence entre signer une fois et
resigner chaque année tout ce qu'on a publié. Jenga horodate toujours ;
`windowstimestampurl()` change seulement le serveur.

**Sur macOS, signer ne suffit pas.** Depuis 10.15, un binaire signé mais non
notarisé s'ouvre avec « impossible de vérifier le développeur ». Et la
notarisation exige le *hardened runtime* : sans lui, la soumission est acceptée
puis rejetée, et le message n'arrive que par courriel. Jenga pose
`--options runtime` par défaut. Le ticket est ensuite **agrafé** au fichier
(`stapler`), sans quoi un utilisateur hors ligne voit encore l'avertissement.

**Le bon certificat Apple.** Pour distribuer hors de l'App Store, il faut un
**Developer ID Application**, pas un « Apple Development ». Les deux signent,
un seul passe Gatekeeper.

---

## Un certificat auto-signé ne sert qu'à tester

Il se pose parfaitement, et il ne vaut rien chez l'utilisateur : sa racine n'est
pas de confiance. Jenga relit la signature après l'avoir posée et le dit
franchement quand la vérification échoue.

Pour Windows, seul un certificat délivré par une autorité reconnue lève
l'alerte :

| Type | Effet | Ordre de grandeur |
|---|---|---|
| **OV** | la réputation se construit sur quelques semaines de téléchargements | 200 à 400 € / an |
| **EV** | réputation SmartScreen **immédiate**, clé sur jeton matériel | 350 à 600 € / an |

En attendant le certificat, deux choses gratuites et efficaces : déclarer le
faux positif sur le portail développeur de Microsoft (réponse en 24 à 72 heures,
correction propagée à tout le parc Defender), et publier le `SHA256SUMS` que
`jenga sign --platform linux` produit pour n'importe quel lot de fichiers, y
compris des `.exe`.

---

## English (summary)

Jenga 2.8.0 signs desktop applications. **The three systems do different
things**: Windows and macOS embed the signature in the file, Linux has no ELF
equivalent and relies on detached GPG signatures plus checksums — Jenga does
what each system actually expects rather than pretending they match.

DSL: `windowssign()` / `windowscertificate()`, `macossign()` /
`macossigningidentity()` / `macosnotaryprofile()`, `linuxsign()` /
`linuxgpgkey()`. CLI: `jenga sign --platform <os> --file A --file B`.

Secrets come from `JENGA_WINDOWS_CERT_PASSWORD` and `JENGA_GPG_PASSPHRASE`, never
from the project file; nothing secret is ever logged. Timestamping is always on:
without it every already-distributed binary becomes untrusted when the
certificate expires. macOS signing without notarization is not enough since
10.15. A self-signed certificate is for testing only — Jenga verifies what it
signed and says so when the chain is not trusted.
