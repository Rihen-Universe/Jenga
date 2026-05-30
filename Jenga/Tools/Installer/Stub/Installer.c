/*
 * Jenga Installer — stub self-extracting multi-plateforme.
 *
 * Ce binaire est compile par Jenga puis se voit accoler un PAYLOAD
 * (manifeste + archive) suivi d'un TRAILER de 80 octets (48 d'entetes +
 * 32 de SHA-256). A l'execution, le stub se lit lui-meme, verifie le
 * SHA-256 du payload (anti-tampering), extrait les fichiers vers le dossier
 * d'installation, configure le pare-feu et ecrit un desinstalleur.
 *
 * Format : voir Jenga/Tools/Installer/DESIGN.md.
 * Edite par Rihen — fait partie de Jenga.
 *
 * Nomenclature : fonctions/types en PascalCase, variables locales en camelCase,
 * constantes/macros en UPPER_SNAKE_CASE.
 *
 * C99 portable. Specificites OS isolees par #ifdef (_WIN32 / __APPLE__ / autre).
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <ctype.h>

#ifdef _WIN32
  #define COBJMACROS              /* macros C pour COM (IShellLink_SetPath...) */
  #include <windows.h>
  #include <direct.h>
  #include <shlobj.h>             /* IShellLink, SHGetFolderPath, CSIDL_* */
  #include <objbase.h>            /* CoInitialize, CoCreateInstance */
  #define PATH_SEP '\\'
  #define MKDIR(p) _mkdir(p)
#else
  #include <unistd.h>
  #include <sys/stat.h>
  #include <sys/types.h>
  #include <errno.h>
  #define PATH_SEP '/'
  #define MKDIR(p) mkdir((p), 0755)
  #ifdef __APPLE__
    #include <mach-o/dyld.h>
  #endif
#endif

#define TRAILER_MAGIC "JNGINST1"
#define TRAILER_SIZE  80    /* 48 (entetes) + 32 (SHA-256 du payload) */
#define PATH_MAX_LEN  4096

/* ----------------------------------------------------------------------- */
/* Lecture little-endian portable                                          */
/* ----------------------------------------------------------------------- */
static uint64_t RdU64(const unsigned char *p) {
    uint64_t value = 0;
    for (int i = 7; i >= 0; --i) value = (value << 8) | p[i];
    return value;
}
static uint32_t RdU32(const unsigned char *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

/* ----------------------------------------------------------------------- */
/* SHA-256 autonome (anti-tampering). Implementation classique du domaine   */
/* public. Sert a verifier l'integrite du payload AVANT extraction : si le  */
/* binaire a ete altere/infecte, le hash ne correspond plus -> on refuse.   */
/* ----------------------------------------------------------------------- */
typedef struct {
    uint32_t state[8];
    uint64_t bitLen;
    uint8_t  data[64];
    uint32_t dataLen;
} Sha256Ctx;

#define SHA256_ROTR(x, n) (((x) >> (n)) | ((x) << (32 - (n))))

static const uint32_t SHA256_K[64] = {
    0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
    0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
    0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2
};

static void Sha256Transform(Sha256Ctx *ctx, const uint8_t *data) {
    uint32_t a, b, c, d, e, f, g, h, t1, t2, m[64];
    int i, j;
    for (i = 0, j = 0; i < 16; ++i, j += 4)
        m[i] = ((uint32_t)data[j] << 24) | ((uint32_t)data[j + 1] << 16) |
               ((uint32_t)data[j + 2] << 8) | ((uint32_t)data[j + 3]);
    for (; i < 64; ++i) {
        uint32_t s0 = SHA256_ROTR(m[i-15], 7) ^ SHA256_ROTR(m[i-15], 18) ^ (m[i-15] >> 3);
        uint32_t s1 = SHA256_ROTR(m[i-2], 17) ^ SHA256_ROTR(m[i-2], 19) ^ (m[i-2] >> 10);
        m[i] = m[i-16] + s0 + m[i-7] + s1;
    }
    a = ctx->state[0]; b = ctx->state[1]; c = ctx->state[2]; d = ctx->state[3];
    e = ctx->state[4]; f = ctx->state[5]; g = ctx->state[6]; h = ctx->state[7];
    for (i = 0; i < 64; ++i) {
        uint32_t bigS1 = SHA256_ROTR(e, 6) ^ SHA256_ROTR(e, 11) ^ SHA256_ROTR(e, 25);
        uint32_t ch = (e & f) ^ (~e & g);
        t1 = h + bigS1 + ch + SHA256_K[i] + m[i];
        uint32_t bigS0 = SHA256_ROTR(a, 2) ^ SHA256_ROTR(a, 13) ^ SHA256_ROTR(a, 22);
        uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
        t2 = bigS0 + maj;
        h = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
    }
    ctx->state[0] += a; ctx->state[1] += b; ctx->state[2] += c; ctx->state[3] += d;
    ctx->state[4] += e; ctx->state[5] += f; ctx->state[6] += g; ctx->state[7] += h;
}

static void Sha256Init(Sha256Ctx *ctx) {
    ctx->dataLen = 0; ctx->bitLen = 0;
    ctx->state[0] = 0x6a09e667; ctx->state[1] = 0xbb67ae85;
    ctx->state[2] = 0x3c6ef372; ctx->state[3] = 0xa54ff53a;
    ctx->state[4] = 0x510e527f; ctx->state[5] = 0x9b05688c;
    ctx->state[6] = 0x1f83d9ab; ctx->state[7] = 0x5be0cd19;
}

static void Sha256Update(Sha256Ctx *ctx, const uint8_t *data, size_t len) {
    for (size_t i = 0; i < len; ++i) {
        ctx->data[ctx->dataLen++] = data[i];
        if (ctx->dataLen == 64) {
            Sha256Transform(ctx, ctx->data);
            ctx->bitLen += 512;
            ctx->dataLen = 0;
        }
    }
}

static void Sha256Final(Sha256Ctx *ctx, uint8_t hash[32]) {
    uint32_t i = ctx->dataLen;
    ctx->data[i++] = 0x80;
    if (ctx->dataLen < 56) {
        while (i < 56) ctx->data[i++] = 0x00;
    } else {
        while (i < 64) ctx->data[i++] = 0x00;
        Sha256Transform(ctx, ctx->data);
        memset(ctx->data, 0, 56);
    }
    ctx->bitLen += (uint64_t)ctx->dataLen * 8;
    for (int k = 0; k < 8; ++k)
        ctx->data[63 - k] = (uint8_t)(ctx->bitLen >> (8 * k));
    Sha256Transform(ctx, ctx->data);
    for (i = 0; i < 8; ++i)
        for (int k = 0; k < 4; ++k)
            hash[i * 4 + k] = (uint8_t)(ctx->state[i] >> (24 - k * 8));
}

/* ----------------------------------------------------------------------- */
/* Chemin du binaire courant                                               */
/* ----------------------------------------------------------------------- */
static int GetSelfPath(char *buf, size_t n) {
#ifdef _WIN32
    DWORD r = GetModuleFileNameA(NULL, buf, (DWORD)n);
    return (r > 0 && r < n) ? 0 : -1;
#elif defined(__APPLE__)
    uint32_t sz = (uint32_t)n;
    return _NSGetExecutablePath(buf, &sz) == 0 ? 0 : -1;
#else
    ssize_t r = readlink("/proc/self/exe", buf, n - 1);
    if (r <= 0) return -1;
    buf[r] = '\0';
    return 0;
#endif
}

/* ----------------------------------------------------------------------- */
/* Creation recursive de dossiers (mkdir -p)                               */
/* ----------------------------------------------------------------------- */
static void MkdirP(const char *path) {
    char tmp[PATH_MAX_LEN];
    size_t len = strlen(path);
    if (len == 0 || len >= sizeof(tmp)) return;
    strcpy(tmp, path);
    for (size_t i = 1; i < len; ++i) {
        if (tmp[i] == '/' || tmp[i] == '\\') {
            char c = tmp[i];
            tmp[i] = '\0';
            MKDIR(tmp);
            tmp[i] = c;
        }
    }
    MKDIR(tmp);
}

/* Normalise les separateurs vers ceux de l'OS. */
static void ToNativeSep(char *s) {
    for (; *s; ++s)
        if (*s == '/' || *s == '\\') *s = PATH_SEP;
}

/* ----------------------------------------------------------------------- */
/* Manifeste : recherche d'une cle "cle=valeur" (1er match).               */
/* ----------------------------------------------------------------------- */
static int ManifestGet(const char *manifest, const char *key, char *out, size_t n) {
    size_t keyLen = strlen(key);
    const char *cursor = manifest;
    while (*cursor) {
        const char *line = cursor;
        const char *eol = strchr(cursor, '\n');
        size_t lineLen = eol ? (size_t)(eol - line) : strlen(line);
        if (lineLen > keyLen && strncmp(line, key, keyLen) == 0 && line[keyLen] == '=') {
            size_t valueLen = lineLen - keyLen - 1;
            if (valueLen >= n) valueLen = n - 1;
            memcpy(out, line + keyLen + 1, valueLen);
            out[valueLen] = '\0';
            if (valueLen > 0 && out[valueLen - 1] == '\r') out[valueLen - 1] = '\0';
            return 0;
        }
        if (!eol) break;
        cursor = eol + 1;
    }
    return -1;
}

/* Expansion basique des variables d'environnement dans un chemin. */
static void ExpandPath(const char *in, char *out, size_t n) {
#ifdef _WIN32
    ExpandEnvironmentStringsA(in, out, (DWORD)n);
#else
    out[0] = '\0';
    size_t outIdx = 0;
    for (size_t i = 0; in[i] && outIdx + 1 < n; ) {
        if (in[i] == '~' && i == 0) {
            const char *home = getenv("HOME");
            if (home) {
                size_t homeLen = strlen(home);
                if (outIdx + homeLen < n) { strcpy(out + outIdx, home); outIdx += homeLen; }
            }
            i++;
        } else if (in[i] == '$') {
            char varName[256];
            size_t varIdx = 0;
            i++;
            while (in[i] && (isalnum((unsigned char)in[i]) || in[i] == '_') && varIdx < 255)
                varName[varIdx++] = in[i++];
            varName[varIdx] = '\0';
            const char *value = getenv(varName);
            if (value) {
                size_t valueLen = strlen(value);
                if (outIdx + valueLen < n) { strcpy(out + outIdx, value); outIdx += valueLen; }
            }
        } else {
            out[outIdx++] = in[i++];
        }
    }
    out[outIdx] = '\0';
#endif
}

/* Remplace toutes les occurrences de `token` par `value` dans `buf`. Sert a
 * substituer {exe} (chemin de l'exe installe, connu au runtime) dans les
 * commandes pare-feu du manifeste. */
static void ReplacePlaceholder(char *buf, size_t bufSize, const char *token, const char *value) {
    char tmp[4096];
    size_t tokenLen = strlen(token), valueLen = strlen(value);
    char *pos = strstr(buf, token);
    while (pos) {
        size_t prefixLen = (size_t)(pos - buf);
        if (prefixLen + valueLen + strlen(pos + tokenLen) >= bufSize) break;
        snprintf(tmp, sizeof(tmp), "%.*s%s%s", (int)prefixLen, buf, value, pos + tokenLen);
        strncpy(buf, tmp, bufSize - 1);
        buf[bufSize - 1] = '\0';
        pos = strstr(buf, token);
    }
}

/* ----------------------------------------------------------------------- */
/* Extraction de l'archive : lit `entries` fichiers depuis fp (positionne  */
/* au debut de l'archive). Ecrit la liste des fichiers poses dans `listFp`. */
/* ----------------------------------------------------------------------- */
static int ExtractArchive(FILE *fp, uint64_t entries, const char *destDir,
                          FILE *listFp, int verbose) {
    char path[PATH_MAX_LEN], full[PATH_MAX_LEN];
    char *dataBuf = NULL;
    size_t dataBufCap = 0;

    for (uint64_t e = 0; e < entries; ++e) {
        unsigned char u32b[4], u64b[8];
        if (fread(u32b, 1, 4, fp) != 4) { free(dataBuf); return -1; }
        uint32_t pathLen = RdU32(u32b);
        if (pathLen == 0 || pathLen >= sizeof(path)) { free(dataBuf); return -1; }
        if (fread(path, 1, pathLen, fp) != pathLen) { free(dataBuf); return -1; }
        path[pathLen] = '\0';
        if (fread(u32b, 1, 4, fp) != 4) { free(dataBuf); return -1; }
        uint32_t mode = RdU32(u32b);
        if (fread(u64b, 1, 8, fp) != 8) { free(dataBuf); return -1; }
        uint64_t size = RdU64(u64b);

        snprintf(full, sizeof(full), "%s%c%s", destDir, PATH_SEP, path);
        ToNativeSep(full);

        /* creer le dossier parent */
        char parent[PATH_MAX_LEN];
        strcpy(parent, full);
        for (int i = (int)strlen(parent) - 1; i >= 0; --i) {
            if (parent[i] == PATH_SEP) { parent[i] = '\0'; break; }
        }
        MkdirP(parent);

        FILE *out = fopen(full, "wb");
        if (!out) { fprintf(stderr, "  [ERREUR] ecriture %s\n", full); free(dataBuf); return -1; }
        if (size > dataBufCap) {
            char *grown = (char *)realloc(dataBuf, (size_t)size);
            if (!grown) { fclose(out); free(dataBuf); return -1; }
            dataBuf = grown; dataBufCap = (size_t)size;
        }
        if (size > 0) {
            if (fread(dataBuf, 1, (size_t)size, fp) != size) { fclose(out); free(dataBuf); return -1; }
            fwrite(dataBuf, 1, (size_t)size, out);
        }
        fclose(out);

#ifndef _WIN32
        if (mode != 0) chmod(full, (mode_t)mode);
#else
        (void)mode;
#endif
        if (listFp) fprintf(listFp, "%s\n", path);
        if (verbose) printf("  + %s\n", path);
    }
    free(dataBuf);
    return 0;
}

/* ----------------------------------------------------------------------- */
/* Raccourcis (menu / bureau) + enregistrement desinstallation OS          */
/* ----------------------------------------------------------------------- */

/* Chemin du raccourci MENU pour `name`. 0 si OK, -1 si non supporte. */
static int MenuShortcutPath(const char *name, char *out, size_t n) {
#ifdef _WIN32
    char base[PATH_MAX_LEN];
    if (SHGetFolderPathA(NULL, CSIDL_PROGRAMS, NULL, 0, base) != S_OK) return -1;
    snprintf(out, n, "%s\\%s.lnk", base, name);
    return 0;
#elif defined(__APPLE__)
    (void)name; (void)out; (void)n; return -1;     /* pas de "menu" sur macOS */
#else
    const char *home = getenv("HOME");
    if (!home) return -1;
    snprintf(out, n, "%s/.local/share/applications/%s.desktop", home, name);
    return 0;
#endif
}

/* Chemin du raccourci BUREAU pour `name`. 0 si OK, -1 si non supporte. */
static int DesktopShortcutPath(const char *name, char *out, size_t n) {
#ifdef _WIN32
    char base[PATH_MAX_LEN];
    if (SHGetFolderPathA(NULL, CSIDL_DESKTOPDIRECTORY, NULL, 0, base) != S_OK) return -1;
    snprintf(out, n, "%s\\%s.lnk", base, name);
    return 0;
#elif defined(__APPLE__)
    (void)name; (void)out; (void)n; return -1;
#else
    const char *home = getenv("HOME");
    if (!home) return -1;
    snprintf(out, n, "%s/Desktop/%s.desktop", home, name);
    return 0;
#endif
}

/* Cree un raccourci `shortcutPath` vers `target`. 0 si OK. */
static int CreateShortcut(const char *target, const char *shortcutPath,
                          const char *workDir, const char *iconPath, const char *name) {
#ifdef _WIN32
    (void)name;
    IShellLinkA *psl = NULL; IPersistFile *ppf = NULL;
    HRESULT hr; int ok = -1;
    CoInitialize(NULL);
    hr = CoCreateInstance(&CLSID_ShellLink, NULL, CLSCTX_INPROC_SERVER,
                          &IID_IShellLinkA, (void **)&psl);
    if (SUCCEEDED(hr)) {
        IShellLinkA_SetPath(psl, target);
        if (workDir && workDir[0]) IShellLinkA_SetWorkingDirectory(psl, workDir);
        if (iconPath && iconPath[0]) IShellLinkA_SetIconLocation(psl, iconPath, 0);
        hr = IShellLinkA_QueryInterface(psl, &IID_IPersistFile, (void **)&ppf);
        if (SUCCEEDED(hr)) {
            WCHAR wide[PATH_MAX_LEN];
            MultiByteToWideChar(CP_ACP, 0, shortcutPath, -1, wide, PATH_MAX_LEN);
            if (SUCCEEDED(IPersistFile_Save(ppf, wide, TRUE))) ok = 0;
            IPersistFile_Release(ppf);
        }
        IShellLinkA_Release(psl);
    }
    CoUninitialize();
    return ok;
#elif defined(__APPLE__)
    (void)workDir; (void)iconPath; (void)name;
    unlink(shortcutPath);
    return symlink(target, shortcutPath);
#else
    (void)workDir;
    FILE *f = fopen(shortcutPath, "wb");
    if (!f) return -1;
    fprintf(f, "[Desktop Entry]\nType=Application\nName=%s\nExec=\"%s\"\nTerminal=false\n",
            name ? name : "App", target);
    if (iconPath && iconPath[0]) fprintf(f, "Icon=%s\n", iconPath);
    fclose(f);
    chmod(shortcutPath, 0755);
    return 0;
#endif
}

/* Enregistre l'app pour la desinstallation OS (Windows : registre Uninstall). */
static void RegisterUninstall(const char *name, const char *version,
                              const char *publisher, const char *installDir,
                              const char *uninstaller, const char *iconPath) {
#ifdef _WIN32
    char subkey[PATH_MAX_LEN];
    snprintf(subkey, sizeof(subkey),
             "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\%s", name);
    HKEY hk;
    if (RegCreateKeyExA(HKEY_CURRENT_USER, subkey, 0, NULL, 0, KEY_WRITE, NULL, &hk, NULL) != ERROR_SUCCESS)
        return;
    #define JNG_REGSTR(k, v) RegSetValueExA(hk, (k), 0, REG_SZ, (const BYTE *)(v), (DWORD)strlen(v) + 1)
    JNG_REGSTR("DisplayName", name);
    JNG_REGSTR("DisplayVersion", version);
    JNG_REGSTR("Publisher", publisher);
    JNG_REGSTR("InstallLocation", installDir);
    JNG_REGSTR("UninstallString", uninstaller);
    if (iconPath && iconPath[0]) JNG_REGSTR("DisplayIcon", iconPath);
    #undef JNG_REGSTR
    DWORD one = 1;
    RegSetValueExA(hk, "NoModify", 0, REG_DWORD, (const BYTE *)&one, sizeof(one));
    RegSetValueExA(hk, "NoRepair", 0, REG_DWORD, (const BYTE *)&one, sizeof(one));
    RegCloseKey(hk);
#else
    (void)name; (void)version; (void)publisher;
    (void)installDir; (void)uninstaller; (void)iconPath;
#endif
}

/* ----------------------------------------------------------------------- */
/* Ecrit le desinstalleur (script) : retire la cle de registre, la regle    */
/* pare-feu, les raccourcis, puis les fichiers installes.                   */
/* ----------------------------------------------------------------------- */
static void WriteUninstaller(const char *destDir, const char *fwDel, const char *name,
                             char shortcuts[][PATH_MAX_LEN], int nShortcuts) {
    char path[PATH_MAX_LEN];
#ifdef _WIN32
    snprintf(path, sizeof(path), "%s%cuninstall.bat", destDir, PATH_SEP);
    FILE *u = fopen(path, "wb");
    if (!u) return;
    fprintf(u, "@echo off\r\n");
    fprintf(u, "REM Desinstalleur genere par Jenga Installer\r\n");
    fprintf(u, "reg delete \"HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\%s\" /f >nul 2>&1\r\n", name);
    if (fwDel && fwDel[0]) fprintf(u, "%s >nul 2>&1\r\n", fwDel);
    for (int i = 0; i < nShortcuts; ++i)
        fprintf(u, "del /f /q \"%s\" >nul 2>&1\r\n", shortcuts[i]);
    fprintf(u, "for /f \"usebackq delims=\" %%%%F in (\"%s%cuninstall.files\") do del /f /q \"%s%c%%%%F\" >nul 2>&1\r\n",
            destDir, PATH_SEP, destDir, PATH_SEP);
    fprintf(u, "echo Desinstalle.\r\n");
    fclose(u);
#else
    (void)name;
    snprintf(path, sizeof(path), "%s%cuninstall.sh", destDir, PATH_SEP);
    FILE *u = fopen(path, "wb");
    if (!u) return;
    fprintf(u, "#!/bin/sh\n# Desinstalleur genere par Jenga Installer\n");
    if (fwDel && fwDel[0]) fprintf(u, "%s >/dev/null 2>&1 || true\n", fwDel);
    for (int i = 0; i < nShortcuts; ++i)
        fprintf(u, "rm -f \"%s\"\n", shortcuts[i]);
    fprintf(u, "DIR=\"$(cd \"$(dirname \"$0\")\" && pwd)\"\n");
    fprintf(u, "while IFS= read -r f; do rm -f \"$DIR/$f\"; done < \"$DIR/uninstall.files\"\n");
    fprintf(u, "echo Desinstalle.\n");
    fclose(u);
    chmod(path, 0755);
#endif
}

/* ----------------------------------------------------------------------- */
/* Point d'entree                                                           */
/* ----------------------------------------------------------------------- */
int main(int argc, char **argv) {
    const char *optDir = NULL;
    int silent = 0;
    for (int i = 1; i < argc; ++i) {
        if (strcmp(argv[i], "--dir") == 0 && i + 1 < argc) optDir = argv[++i];
        else if (strcmp(argv[i], "--silent") == 0) silent = 1;
        else if (strcmp(argv[i], "--help") == 0) {
            printf("Jenga Installer\n  --dir <chemin>  dossier d'installation\n"
                   "  --silent        sans interaction\n  --help          aide\n");
            return 0;
        }
    }

    /* 1. self path + ouverture */
    char selfPath[PATH_MAX_LEN];
    if (GetSelfPath(selfPath, sizeof(selfPath)) != 0) { fprintf(stderr, "self path KO\n"); return 1; }
    FILE *fp = fopen(selfPath, "rb");
    if (!fp) { fprintf(stderr, "ouverture self KO\n"); return 1; }

    /* 2. trailer (48 derniers octets) */
    if (fseek(fp, -TRAILER_SIZE, SEEK_END) != 0) { fclose(fp); return 1; }
    unsigned char trailer[TRAILER_SIZE];
    if (fread(trailer, 1, TRAILER_SIZE, fp) != TRAILER_SIZE) { fclose(fp); return 1; }
    if (memcmp(trailer, TRAILER_MAGIC, 8) != 0) {
        fprintf(stderr, "Aucun payload trouve (binaire stub nu ?).\n");
        fclose(fp); return 1;
    }
    uint64_t manifestOff = RdU64(trailer + 8);
    uint64_t manifestSz  = RdU64(trailer + 16);
    uint64_t archiveOff  = RdU64(trailer + 24);
    uint64_t archiveEnt  = RdU64(trailer + 32);
    const unsigned char *expectedHash = trailer + 48;   /* SHA-256 du payload */

    /* 2b. Verification d'integrite (anti-tampering) : on recalcule le SHA-256
     * du payload (de manifestOff jusqu'au debut du trailer) et on le compare
     * a celui stocke. Si le binaire a ete altere/infecte -> refus. */
    fseek(fp, 0, SEEK_END);
    long fileSize = ftell(fp);
    if (fileSize <= 0 || (uint64_t)fileSize < manifestOff + TRAILER_SIZE) {
        fprintf(stderr, "Fichier installateur invalide.\n");
        fclose(fp); return 1;
    }
    {
        Sha256Ctx shaCtx;
        Sha256Init(&shaCtx);
        fseek(fp, (long)manifestOff, SEEK_SET);
        uint64_t remaining = (uint64_t)fileSize - TRAILER_SIZE - manifestOff;
        unsigned char chunk[8192];
        while (remaining > 0) {
            size_t want = remaining < sizeof(chunk) ? (size_t)remaining : sizeof(chunk);
            size_t got = fread(chunk, 1, want, fp);
            if (got == 0) break;
            Sha256Update(&shaCtx, chunk, got);
            remaining -= got;
        }
        uint8_t actualHash[32];
        Sha256Final(&shaCtx, actualHash);
        if (memcmp(actualHash, expectedHash, 32) != 0) {
            fprintf(stderr, "Integrite compromise : le programme d'installation a "
                            "ete altere ou infecte. Abandon.\n");
            fclose(fp); return 1;
        }
    }

    /* 3. manifeste */
    char *manifest = (char *)malloc((size_t)manifestSz + 1);
    if (!manifest) { fclose(fp); return 1; }
    fseek(fp, (long)manifestOff, SEEK_SET);
    if (fread(manifest, 1, (size_t)manifestSz, fp) != manifestSz) { free(manifest); fclose(fp); return 1; }
    manifest[manifestSz] = '\0';

    char name[256] = "App", version[64] = "", publisher[256] = "Rihen";
    ManifestGet(manifest, "name", name, sizeof(name));
    ManifestGet(manifest, "version", version, sizeof(version));
    ManifestGet(manifest, "publisher", publisher, sizeof(publisher));

    /* 4. dossier d'install */
    char destDir[PATH_MAX_LEN];
    if (optDir) {
        strncpy(destDir, optDir, sizeof(destDir) - 1);
        destDir[sizeof(destDir) - 1] = '\0';
    } else {
        char key[64], raw[PATH_MAX_LEN] = "";
#ifdef _WIN32
        strcpy(key, "default_dir_windows");
#elif defined(__APPLE__)
        strcpy(key, "default_dir_macos");
#else
        strcpy(key, "default_dir_linux");
#endif
        if (ManifestGet(manifest, key, raw, sizeof(raw)) != 0)
            snprintf(raw, sizeof(raw), "%s", name);
        ExpandPath(raw, destDir, sizeof(destDir));
    }
    ToNativeSep(destDir);

    printf("=== Installation de %s %s (editeur : %s) ===\n", name, version, publisher);
    printf("Dossier cible : %s\n", destDir);
    if (!silent) {
        printf("Continuer ? [O/n] ");
        fflush(stdout);
        int c = getchar();
        if (c == 'n' || c == 'N') { printf("Annule.\n"); free(manifest); fclose(fp); return 0; }
    }

    MkdirP(destDir);

    /* liste des fichiers installes (pour le desinstalleur) */
    char listPath[PATH_MAX_LEN];
    snprintf(listPath, sizeof(listPath), "%s%cuninstall.files", destDir, PATH_SEP);
    FILE *listFp = fopen(listPath, "wb");

    /* 5. extraction */
    fseek(fp, (long)archiveOff, SEEK_SET);
    int rc = ExtractArchive(fp, archiveEnt, destDir, listFp, !silent);
    if (listFp) fclose(listFp);
    fclose(fp);
    if (rc != 0) { fprintf(stderr, "Extraction echouee.\n"); free(manifest); return 1; }

    /* 6. pare-feu : execute la commande 'add' du manifeste. Le placeholder
     * {exe} y est remplace par le chemin absolu de l'exe installe. */
    char fwAdd[2048] = "", fwDel[2048] = "";
    ManifestGet(manifest, "firewall_add", fwAdd, sizeof(fwAdd));
    ManifestGet(manifest, "firewall_del", fwDel, sizeof(fwDel));
    {
        char exeForFw[256] = "", targetForFw[PATH_MAX_LEN] = "";
        ManifestGet(manifest, "exe", exeForFw, sizeof(exeForFw));
        if (exeForFw[0]) {
            snprintf(targetForFw, sizeof(targetForFw), "%s%c%s", destDir, PATH_SEP, exeForFw);
            ToNativeSep(targetForFw);
            ReplacePlaceholder(fwAdd, sizeof(fwAdd), "{exe}", targetForFw);
            ReplacePlaceholder(fwDel, sizeof(fwDel), "{exe}", targetForFw);
        }
    }
    if (fwAdd[0]) {
        if (!silent) printf("Configuration du pare-feu...\n");
        system(fwAdd);
    }

    /* 7. raccourcis (menu / bureau) selon le manifeste */
    char shortcuts[4][PATH_MAX_LEN];
    int nShortcuts = 0;
    char exe[256] = "", iconRel[PATH_MAX_LEN] = "", wantMenu[8] = "", wantDesktop[8] = "";
    ManifestGet(manifest, "exe", exe, sizeof(exe));
    ManifestGet(manifest, "icon", iconRel, sizeof(iconRel));
    ManifestGet(manifest, "shortcut_menu", wantMenu, sizeof(wantMenu));
    ManifestGet(manifest, "shortcut_desktop", wantDesktop, sizeof(wantDesktop));

    char targetExe[PATH_MAX_LEN] = "", iconAbs[PATH_MAX_LEN] = "";
    if (exe[0]) {
        snprintf(targetExe, sizeof(targetExe), "%s%c%s", destDir, PATH_SEP, exe);
        ToNativeSep(targetExe);
    }
    if (iconRel[0]) {
        snprintf(iconAbs, sizeof(iconAbs), "%s%c%s", destDir, PATH_SEP, iconRel);
        ToNativeSep(iconAbs);
    }
    if (exe[0] && wantMenu[0] == '1') {
        char sc[PATH_MAX_LEN];
        if (MenuShortcutPath(name, sc, sizeof(sc)) == 0 &&
            CreateShortcut(targetExe, sc, destDir, iconAbs, name) == 0) {
            strncpy(shortcuts[nShortcuts++], sc, PATH_MAX_LEN - 1);
            if (!silent) printf("Raccourci menu : %s\n", sc);
        }
    }
    if (exe[0] && wantDesktop[0] == '1') {
        char sc[PATH_MAX_LEN];
        if (DesktopShortcutPath(name, sc, sizeof(sc)) == 0 &&
            CreateShortcut(targetExe, sc, destDir, iconAbs, name) == 0) {
            strncpy(shortcuts[nShortcuts++], sc, PATH_MAX_LEN - 1);
            if (!silent) printf("Raccourci bureau : %s\n", sc);
        }
    }

    /* 8. enregistrement desinstallation OS (registre Windows) */
    char uninstallerPath[PATH_MAX_LEN];
#ifdef _WIN32
    snprintf(uninstallerPath, sizeof(uninstallerPath), "%s%cuninstall.bat", destDir, PATH_SEP);
#else
    snprintf(uninstallerPath, sizeof(uninstallerPath), "%s%cuninstall.sh", destDir, PATH_SEP);
#endif
    RegisterUninstall(name, version[0] ? version : "1.0.0", publisher,
                      destDir, uninstallerPath, iconAbs);

    /* 9. desinstalleur (retire registre + firewall + raccourcis + fichiers) */
    WriteUninstaller(destDir, fwDel, name, shortcuts, nShortcuts);

    free(manifest);
    printf("Installation terminee dans : %s\n", destDir);
    return 0;
}
