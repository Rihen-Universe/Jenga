# Guide GitHub: passer de HTTPS+token vers SSH

## Pourquoi supprimer le token deja present

Un token GitHub dans une URL (ex: `https://ghp_xxx@github.com/...`) est considere comme **compromis**.

Raisons:
- Il peut rester visible dans `.git/config`.
- Il peut etre recupere via historique terminal, logs, captures d'ecran, copier/coller.
- S'il a des droits `repo`, un tiers peut lire/pusher/supprimer du code selon ses permissions.

Conclusion: il faut le **revoquer immediatement**, puis passer a SSH pour ne plus mettre de secret dans les URLs Git.

## Etape 1: revoquer l'ancien token

Dans GitHub:
- `Settings`
- `Developer settings`
- `Personal access tokens` (classic ou fine-grained)
- Trouver le token expose
- `Revoke` / `Delete`

## Etape 2: enlever le token de l'URL remote

Dans le repo:

```powershell
git remote set-url origin https://github.com/Rihen-Universe/Jenga.git
git remote -v
```

Le remote ne doit plus contenir `ghp_...`.

## Etape 3: nettoyer les identifiants en cache (Windows)

### Option terminal

```powershell
cmdkey /list | findstr github
cmdkey /delete:git:https://github.com
```

### Option interface
- Ouvrir `Gestionnaire d'identification`
- `Informations d'identification Windows`
- Supprimer les entrees liees a `github.com`

## Etape 4: generer une cle SSH

```powershell
ssh-keygen -t ed25519 -C "rihen.universe@gmail.com"
```

Accepter le chemin par defaut (`C:\Users\<toi>\.ssh\id_ed25519`) et definir une passphrase.

## Etape 5: demarrer l'agent SSH et charger la cle

```powershell
Get-Service ssh-agent | Set-Service -StartupType Automatic
Start-Service ssh-agent
ssh-add $env:USERPROFILE\.ssh\id_ed25519
```

## Etape 6: ajouter la cle publique dans GitHub

Afficher la cle publique:

```powershell
Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub
```

Puis dans GitHub:
- `Settings`
- `SSH and GPG keys`
- `New SSH key`
- Coller le contenu `.pub`

## Etape 7: tester la connexion SSH

```powershell
ssh -T git@github.com
```

Tu dois voir un message du type: authentification reussie.

## Etape 8: basculer le remote en SSH

```powershell
git remote set-url origin git@github.com:Rihen-Universe/Jenga.git
git remote -v
```

## Etape 9: verifier fetch/push

```powershell
git fetch origin
git push origin main
```

## Resume

- Le token expose doit etre supprime car il est potentiellement utilisable par un tiers.
- SSH evite de stocker des secrets dans les URLs Git.
- Une fois SSH en place, le workflow Git est plus sur et plus propre.
