<div align="center">

# Rihen

**Rêvons ensemble, réinventons le futur.**

*Depuis Yaoundé, au Cameroun, nous écrivons les fondations dont un créateur a
besoin : un écosystème C++ bas niveau, son système de build, son atelier. Du
code écrit à la main, pour que la technologie porte aussi nos histoires.*

<sub>Technologie · Culture · Création</sub>

</div>

---

## La techno-culture, concrètement

Nos outils portent des noms d'ici — **Nkentseu**, **Songo'o**, **Nkoung**,
**Mou** — parce qu'ils ne sont pas la traduction d'un modèle importé. Le pari
est simple à énoncer et long à tenir : une deep tech africaine qui **produit ses
propres fondations** plutôt que d'assembler celles des autres. C'est plus dur,
et c'est le seul chemin qui laisse quelque chose derrière lui.

Concrètement, cela veut dire écrire soi-même les conteneurs, les allocateurs, le
rendu, l'audio, le réseau, le compilateur de shaders — puis raconter ce qu'on y
apprend, ratés compris.

---

## Par où commencer

| | Projet | Ce que c'est | Où ça en est |
|---|---|---|---|
| 🧩 | **[Nkentseu](https://github.com/Rihen-Universe/Nkentseu)** | L'**écosystème C++ zéro-STL** : ~54 modules en 5 couches — conteneurs, allocateurs, fenêtrage, RHI, rendu, audio, réseau, IA — sur 8 plateformes | Foundation, System et Runtime tournent aujourd'hui |
| 🧱 | **[Jenga](https://github.com/Rihen-Universe/Jenga)** | Le **système de build** C/C++ piloté par un DSL Python. Compile directement via les toolchains natives, sans générer de CMake ni de Makefile | v2.1.1 · [wiki bilingue FR/EN](https://github.com/Rihen-Universe/Jenga/wiki) |
| 💻 | **[NKCode](https://github.com/Rihen-Universe/NKCode-Beta)** | L'**atelier** : IDE natif pour C/C++ — éditeur, diagnostics temps réel, débogueur, agents IA intégrés | Bêta publique Windows · [dernière version](https://github.com/Rihen-Universe/NKCode-Beta/releases) |

**Noge**, le moteur de jeu bâti au-dessus de Nkentseu, est en cours : le
squelette est posé, l'essentiel reste à écrire. Nous préférons le dire.

**Plateformes visées** — Windows · Linux · macOS · Android · iOS · Web
(WebAssembly) · HarmonyOS.

### Selon ce que vous cherchez

- **Vous découvrez** → le [README de Nkentseu](https://github.com/Rihen-Universe/Nkentseu#readme) décrit l'architecture en couches.
- **Vous voulez compiler du C/C++ autrement** → le [wiki de Jenga](https://github.com/Rihen-Universe/Jenga/wiki), de l'installation jusqu'au packaging.
- **Vous voulez essayer** → les [bêtas de NKCode](https://github.com/Rihen-Universe/NKCode-Beta/releases). Un rapport de bug nous vaut mieux qu'un encouragement.

---

## Les dépôts satellites

`NKGlad` · `NKGLSlang` · `NKSPIRVCross` · `NKShaderc` · `NKAssimp` ·
`ImGui` · `Vulkan-Headers`

Ce sont des **rempaquetages** de bibliothèques tierces (Khronos, Google,
ocornut, Assimp) adaptés au build Jenga. Les licences amont sont **inchangées**
et le crédit revient à leurs auteurs — nous n'y ajoutons qu'un fichier `.jenga`.

---

## Licences — en toute transparence

Nkentseu et Jenga sont aujourd'hui sous **licence propriétaire**. Une bascule
vers l'open source est prévue, mais elle n'est pas faite : mieux vaut l'écrire
noir sur blanc que de laisser croire à un dépôt ouvert aux contributions de
code.

Ce qui est **déjà ouvert et utile** : la documentation, les wikis, les rapports
de bug, les discussions techniques — et les bêtas, à essayer librement.

---

## Nous écrire

**TEUGUIA TADJUIDJE Rodolf Séderis** — CEO & co-fondateur de Rihen
📧 <rihen.universe@gmail.com> · chaînes **@rihenuniverse**

Un message qui dit « ça casse ici » fait avancer le projet plus qu'un million de
vues. Si vous testez, si vous cassez quelque chose, si vous croyez en une deep
tech africaine — écrivez-nous.

---

<div align="center">
<sub>

**English** — Rihen builds creation tools from Yaoundé, Cameroon: a zero-STL C++
ecosystem (**Nkentseu**, ~54 modules across 5 layers), a Python-driven C/C++
build system (**Jenga**), and a native IDE (**NKCode**). Hand-written low-level
code, so that technology carries our stories too. The ecosystem and the build
system are currently under a **proprietary licence** — an open-source switch is
planned but not done yet. Documentation, wikis and public betas are open to
everyone.

</sub>
</div>
