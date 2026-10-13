#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Docs command – Génère la documentation des projets à partir des commentaires Doxygen.
Analyse le code C++, extrait les signatures et les commentaires, produit des pages Markdown/HTML/PDF.
Fonctionnalités complètes : extraction, statistiques, listing, nettoyage.
Format supportés : markdown, html, pdf, all.
"""

import argparse
import sys
import re
import io
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
import json
import shutil
import time
from datetime import datetime

from ..Utils import Colored, Display, FileSystem
from ..Core.Loader import Loader
from ..Core.Cache import Cache
from ..Core import Api

# Fix encoding for Windows terminals that don't support UTF-8
# (2.8.19) sys.stdout et sys.stderr valent None sans console (pythonw, application fenetree qui
# lance Jenga) : ce module doit quand meme s'importer. Avant : `if sys.stdout.encoding and ...`.
_encodage_sortie = getattr(sys.stdout, 'encoding', None)
if _encodage_sortie and _encodage_sortie.lower() not in ('utf-8', 'utf8'):
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        if sys.stderr is not None:
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

# ============================================================================
# TYPES D'ÉLÉMENTS C++
# ============================================================================

class ElementType(Enum):
    """Types d'éléments C++ reconnus"""
    CLASS = "class"
    STRUCT = "struct"
    ENUM = "enum"
    UNION = "union"
    FUNCTION = "function"
    METHOD = "method"
    VARIABLE = "variable"
    MACRO = "macro"
    TYPEDEF = "typedef"
    NAMESPACE = "namespace"
    
    def __lt__(self, other):
        return self.value < other.value


@dataclass
class Parameter:
    """Paramètre de fonction"""
    name: str
    type: str
    description: str = ""
    direction: str = ""  # in, out, in/out
    default_value: str = ""


@dataclass
class ElementSignature:
    """Signature complète d'un élément C++"""
    element_type: ElementType
    name: str
    full_signature: str  # Signature complète comme dans le code
    return_type: str = ""
    parameters: List[Parameter] = field(default_factory=list)
    template_params: List[str] = field(default_factory=list)
    namespace: str = ""
    parent_class: str = ""  # Pour les méthodes
    
    # Modifiers
    is_const: bool = False
    is_static: bool = False
    is_virtual: bool = False
    is_override: bool = False
    is_final: bool = False
    is_inline: bool = False
    is_explicit: bool = False
    is_constexpr: bool = False
    is_noexcept: bool = False
    is_pure_virtual: bool = False
    
    access: str = "public"  # public, private, protected


@dataclass
class DocComment:
    """Commentaire de documentation Doxygen"""
    signature: ElementSignature
    brief: str = ""
    description: str = ""
    param_docs: Dict[str, str] = field(default_factory=dict)
    returns: str = ""
    return_values: Dict[str, str] = field(default_factory=dict)
    throws: List[str] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    see_also: List[str] = field(default_factory=list)
    since: str = ""
    deprecated: str = ""
    author: str = ""
    date: str = ""
    complexity: str = ""
    thread_safety: str = ""
    
    # Métadonnées de localisation
    file_path: str = ""
    line_number: int = 0


# ============================================================================
# STRUCTURES D'INDEXATION
# ============================================================================

@dataclass
class FileDocumentation:
    """Documentation complète d'un fichier"""
    file_path: Path
    file_name: str
    relative_path: str  # Relatif au workspace
    
    # En-tête du fichier
    file_description: str = ""
    file_author: str = ""
    file_date: str = ""
    
    # Éléments documentés
    elements: List[DocComment] = field(default_factory=list)
    
    # Métadonnées
    namespaces: List[str] = field(default_factory=list)
    includes: List[str] = field(default_factory=list)
    forward_declarations: List[str] = field(default_factory=list)
    
    # Relations
    included_by: List[str] = field(default_factory=list)  # Fichiers qui incluent ce fichier


@dataclass
class ProjectDocumentation:
    """Documentation complète d'un projet"""
    project_name: str
    project_path: Path
    
    # Tous les fichiers
    files: List[FileDocumentation] = field(default_factory=list)
    
    # Index par type
    classes: List[DocComment] = field(default_factory=list)
    structs: List[DocComment] = field(default_factory=list)
    enums: List[DocComment] = field(default_factory=list)
    unions: List[DocComment] = field(default_factory=list)
    functions: List[DocComment] = field(default_factory=list)
    methods: List[DocComment] = field(default_factory=list)
    variables: List[DocComment] = field(default_factory=list)
    macros: List[DocComment] = field(default_factory=list)
    typedefs: List[DocComment] = field(default_factory=list)
    
    # Index par namespace
    by_namespace: Dict[str, List[DocComment]] = field(default_factory=dict)
    
    # Index par nom (pour liens)
    by_name: Dict[str, DocComment] = field(default_factory=dict)
    
    # Graphe de dépendances entre fichiers
    file_dependencies: Dict[str, Set[str]] = field(default_factory=dict)
    
    # Statistiques
    stats: Dict[str, int] = field(default_factory=dict)


# ============================================================================
# EXTRACTEUR PRINCIPAL
# ============================================================================

class DocumentationExtractor:
    """Extracteur principal de documentation"""
    
    SUPPORTED_EXTENSIONS = {'.h', '.hpp', '.hxx', '.hh', '.cpp', '.cxx', '.cc', '.c', '.inl', '.ipp', '.tpp'}
    
    def __init__(self, project_name: str, project_path: Path, 
                 include_private: bool = False, verbose: bool = False):
        self.project_name = project_name
        self.project_path = project_path
        self.include_private = include_private
        self.verbose = verbose
        
        # Parsers
        self.signature_parser = CppSignatureParser()
        self.doxygen_parser = DoxygenParser()
        
        # Documentation du projet
        self.project_doc = ProjectDocumentation(
            project_name=project_name,
            project_path=project_path
        )
        
        # Contexte de parsing
        self.current_file: Optional[Path] = None
        self.current_namespace_stack: List[str] = []
        self.current_class_stack: List[str] = []
        self.current_access: str = "public"
    
    def extract(self, source_dirs: List[Path]) -> ProjectDocumentation:
        """Extrait la documentation de tous les fichiers"""
        
        if self.verbose:
            print(f"📚 Extracting documentation for project: {self.project_name}")
        
        # Collecter tous les fichiers
        all_files = self._collect_files(source_dirs)
        
        if self.verbose:
            print(f"📁 Found {len(all_files)} source files")
        
        # Parser chaque fichier
        for i, file_path in enumerate(all_files):
            if self.verbose:
                print(f"  [{i+1}/{len(all_files)}] Processing {file_path.name}...", end='\r')
            
            file_doc = self._parse_file(file_path)
            if file_doc and file_doc.elements:
                self.project_doc.files.append(file_doc)
        
        if self.verbose:
            print()  # Nouvelle ligne après progression
        
        # Construire les index
        self._build_indices()
        
        # Résoudre les liens inter-éléments
        self._resolve_links()
        
        # Analyser les dépendances
        self._analyze_dependencies()
        
        # Calculer les statistiques
        self._calculate_stats()
        
        if self.verbose:
            print(f"✅ Extraction complete:")
            print(f"   - {len(self.project_doc.files)} files with documentation")
            print(f"   - {self.project_doc.stats.get('total_elements', 0)} elements documented")
        
        return self.project_doc
    
    def _collect_files(self, source_dirs: List[Path]) -> List[Path]:
        """Collecte tous les fichiers sources"""
        files = []
        for source_dir in source_dirs:
            if not source_dir.exists():
                if self.verbose:
                    print(f"⚠️  Warning: Directory does not exist: {source_dir}")
                continue
            
            for ext in self.SUPPORTED_EXTENSIONS:
                files.extend(source_dir.rglob(f"*{ext}"))
        
        # Trier pour avoir un ordre déterministe
        return sorted(set(files))
    
    def _parse_file(self, file_path: Path) -> Optional[FileDocumentation]:
        """Parse un fichier source complet"""
        
        self.current_file = file_path
        self.current_namespace_stack = []
        self.current_class_stack = []
        self.current_access = "public"
        
        try:
            content = file_path.read_text(encoding='utf-8')
        except Exception as e:
            if self.verbose:
                print(f"⚠️  Error reading {file_path}: {e}")
            return None
        
        # Créer la documentation du fichier
        try:
            relative_path = file_path.relative_to(self.project_path)
        except ValueError:
            relative_path = Path(file_path.name)
        
        file_doc = FileDocumentation(
            file_path=file_path,
            file_name=file_path.name,
            relative_path=str(relative_path)
        )
        
        # Parser l'en-tête du fichier
        self._parse_file_header(content, file_doc)
        
        # Extraire métadonnées
        file_doc.includes = self._extract_includes(content)
        file_doc.namespaces = self._extract_namespaces(content)
        
        # Trouver tous les commentaires de documentation
        doc_blocks = self._find_documentation_blocks(content)
        
        # Parser chaque bloc
        for comment_text, line_num, code_after in doc_blocks:
            doc_comment = self._parse_documentation_block(
                comment_text, code_after, file_path, line_num
            )
            
            if doc_comment:
                # Filtrer les éléments privés si demandé
                if self.include_private or doc_comment.signature.access == "public":
                    file_doc.elements.append(doc_comment)
        
        return file_doc
    
    def _find_documentation_blocks(self, content: str) -> List[Tuple[str, int, str]]:
        """Trouve tous les blocs de documentation avec le code qui suit"""
        
        blocks = []
        lines = content.split('\n')
        
        # Pattern pour commentaires /** ... */
        doxygen_pattern = re.compile(r'/\*\*(.*?)\*/', re.DOTALL)
        
        for match in doxygen_pattern.finditer(content):
            comment_text = match.group(1)
            line_num = content[:match.start()].count('\n') + 1
            
            # Trouver le code qui suit
            end_pos = match.end()
            remaining_lines = content[end_pos:].split('\n')
            
            # Ignorer les lignes vides et commentaires
            code_lines = []
            for line in remaining_lines[:30]:  # Max 30 lignes
                stripped = line.strip()
                if stripped and not stripped.startswith('//'):
                    code_lines.append(line)
                    if len(code_lines) >= 10:  # Assez pour capturer une signature
                        break
            
            code_after = '\n'.join(code_lines)
            blocks.append((comment_text, line_num, code_after))
        
        # Pattern pour commentaires /// (lignes consécutives)
        i = 0
        while i < len(lines):
            if lines[i].strip().startswith('///'):
                # Début d'un bloc ///
                comment_lines = []
                start_line = i + 1
                
                while i < len(lines) and lines[i].strip().startswith('///'):
                    text = lines[i].strip()[3:].strip()
                    comment_lines.append(text)
                    i += 1
                
                comment_text = '\n'.join(comment_lines)
                
                # Code qui suit
                code_lines = []
                j = i
                while j < len(lines) and len(code_lines) < 10:
                    stripped = lines[j].strip()
                    if stripped and not stripped.startswith('//'):
                        code_lines.append(lines[j])
                    j += 1
                
                code_after = '\n'.join(code_lines)
                blocks.append((comment_text, start_line, code_after))
            else:
                i += 1
        
        return blocks
    
    def _parse_documentation_block(self, comment_text: str, code_after: str,
                                   file_path: Path, line_num: int) -> Optional[DocComment]:
        """Parse un bloc de documentation complet"""
        
        # Mettre à jour le contexte (namespace, classe, access)
        self._update_context(code_after)
        
        # Détecter le type d'élément et parser sa signature
        signature = self._parse_element_signature(code_after)
        
        if not signature:
            return None
        
        # Enrichir la signature avec le contexte
        signature.namespace = "::".join(self.current_namespace_stack)
        signature.access = self.current_access
        
        if self.current_class_stack:
            signature.parent_class = "::".join(self.current_class_stack)
            # Si dans une classe, c'est une méthode
            if signature.element_type == ElementType.FUNCTION:
                signature.element_type = ElementType.METHOD
        
        # Parser le commentaire Doxygen
        doc_comment = self.doxygen_parser.parse(comment_text, signature)
        doc_comment.file_path = str(file_path)
        doc_comment.line_number = line_num
        
        return doc_comment
    
    def _parse_element_signature(self, code: str) -> Optional[ElementSignature]:
        """Détecte et parse la signature d'un élément C++"""
        
        # Essayer de détecter le type d'élément
        code_clean = code.strip()
        
        # Class/Struct
        if re.search(r'\b(class|struct)\b', code_clean):
            return self.signature_parser.parse_signature(code, 'class')
        
        # Enum
        if re.search(r'\benum\b', code_clean):
            return self.signature_parser.parse_signature(code, 'enum')
        
        # Union
        if re.search(r'\bunion\b', code_clean):
            return self.signature_parser.parse_signature(code, 'union')
        
        # Macro
        if code_clean.startswith('#define'):
            return self.signature_parser.parse_signature(code, 'macro')
        
        # Typedef/using
        if re.search(r'\b(typedef|using)\b', code_clean):
            return self.signature_parser.parse_signature(code, 'typedef')
        
        # Function (avec parenthèses et potentiel type de retour)
        if '(' in code_clean and ')' in code_clean:
            # Vérifier que ce n'est pas juste un appel de fonction
            if not code_clean.strip().endswith(';') or '=' not in code_clean:
                return self.signature_parser.parse_signature(code, 'function')
        
        # Variable (dernier recours)
        if ';' in code_clean:
            return self.signature_parser.parse_signature(code, 'variable')
        
        return None
    
    def _update_context(self, code: str):
        """Met à jour le contexte de parsing (namespace, classe, access)"""
        
        # Détecter namespace
        ns_match = re.search(r'namespace\s+([a-zA-Z_]\w*)\s*\{', code)
        if ns_match:
            self.current_namespace_stack.append(ns_match.group(1))
        
        # Détecter class/struct
        class_match = re.search(r'(class|struct)\s+(?:[A-Z_]+\s+)?([a-zA-Z_]\w*)', code)
        if class_match:
            self.current_class_stack.append(class_match.group(2))
            # struct = public par défaut, class = private
            self.current_access = "public" if class_match.group(1) == "struct" else "private"
        
        # Détecter access specifier
        for access in ['public', 'private', 'protected']:
            if f'{access}:' in code:
                self.current_access = access
        
        # Détecter fermeture de scope (approximatif)
        if code.count('}') > code.count('{'):
            # Approximation: fermeture de namespace ou classe
            if self.current_class_stack:
                self.current_class_stack.pop()
            elif self.current_namespace_stack:
                self.current_namespace_stack.pop()
    
    def _parse_file_header(self, content: str, file_doc: FileDocumentation):
        """Parse l'en-tête du fichier"""
        
        lines = content.split('\n')[:50]  # Chercher dans les 50 premières lignes
        
        # Pattern pour en-tête standard
        header_pattern = re.compile(
            r'//\s*-{3,}.*?'
            r'//\s*FICHIER:\s*(.+?)\n'
            r'//\s*DESCRIPTION:\s*(.+?)\n'
            r'//\s*AUTEUR:\s*(.+?)\n'
            r'//\s*DATE:\s*(.+?)\n',
            re.DOTALL
        )
        
        header_text = '\n'.join(lines)
        match = header_pattern.search(header_text)
        
        if match:
            file_doc.file_description = match.group(2).strip()
            file_doc.file_author = match.group(3).strip()
            file_doc.file_date = match.group(4).strip()
    
    def _extract_includes(self, content: str) -> List[str]:
        """Extrait les #include"""
        includes = []
        for match in re.finditer(r'#include\s+[<"](.+?)[>"]', content):
            includes.append(match.group(1))
        return includes
    
    def _extract_namespaces(self, content: str) -> List[str]:
        """Extrait les namespaces déclarés"""
        namespaces = []
        for match in re.finditer(r'namespace\s+([a-zA-Z_]\w*)\s*\{', content):
            ns = match.group(1)
            if ns not in namespaces:
                namespaces.append(ns)
        return namespaces
    
    def _build_indices(self):
        """Construit les index par type, namespace, nom"""
        
        for file_doc in self.project_doc.files:
            for element in file_doc.elements:
                sig = element.signature
                
                # Index par type
                if sig.element_type == ElementType.CLASS:
                    self.project_doc.classes.append(element)
                elif sig.element_type == ElementType.STRUCT:
                    self.project_doc.structs.append(element)
                elif sig.element_type == ElementType.ENUM:
                    self.project_doc.enums.append(element)
                elif sig.element_type == ElementType.UNION:
                    self.project_doc.unions.append(element)
                elif sig.element_type == ElementType.FUNCTION:
                    self.project_doc.functions.append(element)
                elif sig.element_type == ElementType.METHOD:
                    self.project_doc.methods.append(element)
                elif sig.element_type == ElementType.VARIABLE:
                    self.project_doc.variables.append(element)
                elif sig.element_type == ElementType.MACRO:
                    self.project_doc.macros.append(element)
                elif sig.element_type == ElementType.TYPEDEF:
                    self.project_doc.typedefs.append(element)
                
                # Index par namespace
                ns = sig.namespace or "__global__"
                if ns not in self.project_doc.by_namespace:
                    self.project_doc.by_namespace[ns] = []
                self.project_doc.by_namespace[ns].append(element)
                
                # Index par nom (pour liens)
                full_name = f"{ns}::{sig.name}" if ns != "__global__" else sig.name
                self.project_doc.by_name[full_name] = element
                
                # Aussi indexer par nom simple
                if sig.name not in self.project_doc.by_name:
                    self.project_doc.by_name[sig.name] = element
    
    def _resolve_links(self):
        """Résout les liens inter-éléments (@see, types, etc.)"""
        
        for file_doc in self.project_doc.files:
            for element in file_doc.elements:
                # Résoudre les liens @see
                resolved_see = []
                for see_ref in element.see_also:
                    if see_ref in self.project_doc.by_name:
                        resolved_see.append(see_ref)
                    else:
                        resolved_see.append(see_ref)
                element.see_also = resolved_see
    
    def _analyze_dependencies(self):
        """Analyse les dépendances entre fichiers"""
        
        # Construire un index include -> fichier
        file_by_name = {}
        for file_doc in self.project_doc.files:
            file_by_name[file_doc.file_name] = file_doc
            file_by_name[file_doc.relative_path] = file_doc
        
        # Pour chaque fichier, résoudre ses includes
        for file_doc in self.project_doc.files:
            deps = set()
            for include in file_doc.includes:
                include_name = Path(include).name
                if include_name in file_by_name:
                    deps.add(file_by_name[include_name].relative_path)
                elif include in file_by_name:
                    deps.add(include)
            self.project_doc.file_dependencies[file_doc.relative_path] = deps
            
            # Remplir included_by (inverse)
            for dep in deps:
                if dep in file_by_name:
                    file_by_name[dep].included_by.append(file_doc.relative_path)
    
    def _calculate_stats(self):
        """Calcule les statistiques du projet"""
        
        stats = {
            'total_files': len(self.project_doc.files),
            'total_elements': sum(len(f.elements) for f in self.project_doc.files),
            'classes': len(self.project_doc.classes),
            'structs': len(self.project_doc.structs),
            'enums': len(self.project_doc.enums),
            'unions': len(self.project_doc.unions),
            'functions': len(self.project_doc.functions),
            'methods': len(self.project_doc.methods),
            'variables': len(self.project_doc.variables),
            'macros': len(self.project_doc.macros),
            'typedefs': len(self.project_doc.typedefs),
            'namespaces': len(self.project_doc.by_namespace),
        }
        
        # Statistiques avancées
        total_params = sum(
            len(e.signature.parameters) 
            for f in self.project_doc.files 
            for e in f.elements 
            if e.signature.parameters
        )
        stats['total_parameters'] = total_params
        
        functions_with_params = [
            e for f in self.project_doc.files 
            for e in f.elements 
            if e.signature.element_type in [ElementType.FUNCTION, ElementType.METHOD]
        ]
        if functions_with_params:
            stats['avg_params_per_function'] = int(total_params / len(functions_with_params))
        else:
            stats['avg_params_per_function'] = 0
        
        well_documented = sum(
            1 for f in self.project_doc.files 
            for e in f.elements 
            if e.brief and e.description
        )
        stats['well_documented'] = well_documented
        
        if stats['total_elements'] > 0:
            stats['documentation_coverage'] = int((well_documented / stats['total_elements']) * 100)
        else:
            stats['documentation_coverage'] = 0
        
        self.project_doc.stats = stats


# ============================================================================
# PARSER C++ AVANCÉ
# ============================================================================

class CppSignatureParser:
    """Parse les signatures C++ avec précision"""
    
    def __init__(self):
        # Patterns de détection
        self.patterns = {
            'namespace': re.compile(
                r'namespace\s+([a-zA-Z_]\w*)\s*\{',
                re.MULTILINE
            ),
            'class': re.compile(
                r'(?:template\s*<[^>]*>\s*)?'
                r'(?:(class|struct)\s+(?:[A-Z_]+\s+)?([a-zA-Z_]\w*))'
                r'(?:\s*:\s*(?:public|private|protected)\s+[^{]+)?'
                r'\s*\{',
                re.MULTILINE
            ),
            'enum': re.compile(
                r'enum\s+(?:class\s+)?([a-zA-Z_]\w*)\s*(?::\s*\w+)?\s*\{',
                re.MULTILINE
            ),
            'union': re.compile(
                r'union\s+([a-zA-Z_]\w*)\s*\{',
                re.MULTILINE
            ),
            'function': re.compile(
                r'(?:template\s*<[^>]*>\s*)?'
                r'(?:(inline|static|virtual|explicit|constexpr)\s+)*'
                r'([a-zA-Z_]\w*(?:<[^>]*>)?(?:\s*[*&])?)\s+'  # return type
                r'([a-zA-Z_]\w*)\s*'  # function name
                r'\(([^)]*)\)'  # parameters
                r'(?:\s*(const|noexcept|override|final))*'
                r'(?:\s*=\s*0)?'  # pure virtual
                r'\s*[;{]',
                re.MULTILINE
            ),
            'variable': re.compile(
                r'(?:(static|const|constexpr|inline)\s+)*'
                r'([a-zA-Z_]\w*(?:<[^>]*>)?(?:\s*[*&])?)\s+'
                r'([a-zA-Z_]\w*)\s*'
                r'(?:=\s*[^;]+)?\s*;',
                re.MULTILINE
            ),
            'macro': re.compile(
                r'#define\s+([A-Z_]\w*)'
                r'(?:\([^)]*\))?'
                r'(?:\s+(.+))?',
                re.MULTILINE
            ),
            'typedef': re.compile(
                r'(?:typedef\s+(.+?)\s+([a-zA-Z_]\w*))|'
                r'(?:using\s+([a-zA-Z_]\w*)\s*=\s*(.+?))',
                re.MULTILINE
            ),
        }
    
    def parse_signature(self, code: str, element_type: str) -> Optional[ElementSignature]:
        """Parse une signature C++ selon son type"""
        
        if element_type == 'class' or element_type == 'struct':
            return self._parse_class_signature(code, element_type)
        elif element_type == 'enum':
            return self._parse_enum_signature(code)
        elif element_type == 'union':
            return self._parse_union_signature(code)
        elif element_type == 'function':
            return self._parse_function_signature(code)
        elif element_type == 'variable':
            return self._parse_variable_signature(code)
        elif element_type == 'macro':
            return self._parse_macro_signature(code)
        elif element_type == 'typedef':
            return self._parse_typedef_signature(code)
        
        return None
    
    def _parse_class_signature(self, code: str, kind: str) -> Optional[ElementSignature]:
        match = self.patterns['class'].search(code)
        if not match:
            return None
        
        class_type = match.group(1)
        name = match.group(2)
        
        template_params = []
        template_match = re.search(r'template\s*<([^>]+)>', code)
        if template_match:
            template_params = [p.strip() for p in template_match.group(1).split(',')]
        
        inheritance = ""
        inherit_match = re.search(r':\s*((?:(?:public|private|protected)\s+\w+(?:,\s*)?)+)', code)
        if inherit_match:
            inheritance = inherit_match.group(1)
        
        sig = f"template<{', '.join(template_params)}> " if template_params else ""
        sig += f"{class_type} {name}"
        if inheritance:
            sig += f" : {inheritance}"
        
        return ElementSignature(
            element_type=ElementType.CLASS if class_type == 'class' else ElementType.STRUCT,
            name=name,
            full_signature=sig,
            template_params=template_params
        )
    
    def _parse_enum_signature(self, code: str) -> Optional[ElementSignature]:
        match = self.patterns['enum'].search(code)
        if not match:
            return None
        name = match.group(1)
        is_scoped = 'enum class' in code
        underlying_type = ""
        type_match = re.search(r'enum\s+(?:class\s+)?\w+\s*:\s*(\w+)', code)
        if type_match:
            underlying_type = type_match.group(1)
        sig = f"enum {'class ' if is_scoped else ''}{name}"
        if underlying_type:
            sig += f" : {underlying_type}"
        return ElementSignature(
            element_type=ElementType.ENUM,
            name=name,
            full_signature=sig
        )
    
    def _parse_union_signature(self, code: str) -> Optional[ElementSignature]:
        match = self.patterns['union'].search(code)
        if not match:
            return None
        name = match.group(1)
        return ElementSignature(
            element_type=ElementType.UNION,
            name=name,
            full_signature=f"union {name}"
        )
    
    def _parse_function_signature(self, code: str) -> Optional[ElementSignature]:
        match = self.patterns['function'].search(code)
        if not match:
            return None
        
        modifiers_str = match.group(1) or ""
        return_type = match.group(2)
        func_name = match.group(3)
        params_str = match.group(4) or ""
        trailing_str = match.group(5) or ""
        
        parameters = self._parse_parameters(params_str)
        
        is_static = 'static' in modifiers_str
        is_virtual = 'virtual' in modifiers_str
        is_inline = 'inline' in modifiers_str
        is_explicit = 'explicit' in modifiers_str
        is_constexpr = 'constexpr' in modifiers_str
        is_const = 'const' in trailing_str
        is_noexcept = 'noexcept' in trailing_str
        is_override = 'override' in trailing_str
        is_final = 'final' in trailing_str
        is_pure_virtual = '= 0' in code
        
        template_params = []
        template_match = re.search(r'template\s*<([^>]+)>', code)
        if template_match:
            template_params = [p.strip() for p in template_match.group(1).split(',')]
        
        sig = ""
        if template_params:
            sig += f"template<{', '.join(template_params)}> "
        if is_static:
            sig += "static "
        if is_virtual:
            sig += "virtual "
        if is_inline:
            sig += "inline "
        if is_explicit:
            sig += "explicit "
        if is_constexpr:
            sig += "constexpr "
        sig += f"{return_type} {func_name}("
        sig += ", ".join([f"{p.type} {p.name}" for p in parameters])
        sig += ")"
        if is_const:
            sig += " const"
        if is_noexcept:
            sig += " noexcept"
        if is_override:
            sig += " override"
        if is_final:
            sig += " final"
        if is_pure_virtual:
            sig += " = 0"
        
        element_type = ElementType.FUNCTION
        
        return ElementSignature(
            element_type=element_type,
            name=func_name,
            full_signature=sig,
            return_type=return_type,
            parameters=parameters,
            template_params=template_params,
            is_static=is_static,
            is_virtual=is_virtual,
            is_inline=is_inline,
            is_explicit=is_explicit,
            is_constexpr=is_constexpr,
            is_const=is_const,
            is_noexcept=is_noexcept,
            is_override=is_override,
            is_final=is_final,
            is_pure_virtual=is_pure_virtual
        )
    
    def _parse_parameters(self, params_str: str) -> List[Parameter]:
        if not params_str.strip():
            return []
        parameters = []
        param_parts = self._smart_split(params_str, ',')
        for part in param_parts:
            part = part.strip()
            if not part or part == 'void':
                continue
            default_value = ""
            if '=' in part:
                part, default_value = part.split('=', 1)
                part = part.strip()
                default_value = default_value.strip()
            tokens = part.split()
            if len(tokens) >= 2:
                param_name = tokens[-1]
                param_name = param_name.lstrip('*&')
                param_type = ' '.join(tokens[:-1])
            else:
                param_name = ""
                param_type = part
            parameters.append(Parameter(
                name=param_name,
                type=param_type,
                default_value=default_value
            ))
        return parameters
    
    def _smart_split(self, text: str, delimiter: str) -> List[str]:
        parts = []
        current = []
        depth_angle = 0
        depth_paren = 0
        for char in text:
            if char == '<':
                depth_angle += 1
            elif char == '>':
                depth_angle -= 1
            elif char == '(':
                depth_paren += 1
            elif char == ')':
                depth_paren -= 1
            elif char == delimiter and depth_angle == 0 and depth_paren == 0:
                parts.append(''.join(current))
                current = []
                continue
            current.append(char)
        if current:
            parts.append(''.join(current))
        return parts
    
    def _parse_variable_signature(self, code: str) -> Optional[ElementSignature]:
        match = self.patterns['variable'].search(code)
        if not match:
            return None
        modifiers = match.group(1) or ""
        var_type = match.group(2)
        var_name = match.group(3)
        is_static = 'static' in modifiers
        is_const = 'const' in modifiers
        is_constexpr = 'constexpr' in modifiers
        is_inline = 'inline' in modifiers
        sig = ""
        if is_static:
            sig += "static "
        if is_const:
            sig += "const "
        if is_constexpr:
            sig += "constexpr "
        if is_inline:
            sig += "inline "
        sig += f"{var_type} {var_name}"
        return ElementSignature(
            element_type=ElementType.VARIABLE,
            name=var_name,
            full_signature=sig,
            return_type=var_type,
            is_static=is_static,
            is_const=is_const,
            is_constexpr=is_constexpr,
            is_inline=is_inline
        )
    
    def _parse_macro_signature(self, code: str) -> Optional[ElementSignature]:
        match = self.patterns['macro'].search(code)
        if not match:
            return None
        macro_name = match.group(1)
        macro_value = match.group(2) or ""
        sig = f"#define {macro_name}"
        if macro_value:
            sig += f" {macro_value}"
        return ElementSignature(
            element_type=ElementType.MACRO,
            name=macro_name,
            full_signature=sig
        )
    
    def _parse_typedef_signature(self, code: str) -> Optional[ElementSignature]:
        match = self.patterns['typedef'].search(code)
        if not match:
            return None
        if match.group(1):
            original_type = match.group(1)
            alias_name = match.group(2)
            sig = f"typedef {original_type} {alias_name}"
        else:
            alias_name = match.group(3)
            original_type = match.group(4)
            sig = f"using {alias_name} = {original_type}"
        return ElementSignature(
            element_type=ElementType.TYPEDEF,
            name=alias_name,
            full_signature=sig,
            return_type=original_type
        )


# ============================================================================
# PARSER DOXYGEN
# ============================================================================

class DoxygenParser:
    """Parse les commentaires Doxygen"""
    
    def __init__(self):
        self.tag_patterns = {
            'brief': re.compile(r'@brief\s+(.+?)(?=@|\n\n|\*/|\Z)', re.DOTALL),
            'class': re.compile(r'@class\s+(\w+)', re.MULTILINE),
            'struct': re.compile(r'@struct\s+(\w+)', re.MULTILINE),
            'enum': re.compile(r'@enum\s+(\w+)', re.MULTILINE),
            'union': re.compile(r'@union\s+(\w+)', re.MULTILINE),
            'function': re.compile(r'@(?:function|fn)\s+(\w+)', re.MULTILINE),
            'var': re.compile(r'@var\s+(.+)', re.MULTILINE),
            'macro': re.compile(r'@(?:macro|def)\s+(\w+)', re.MULTILINE),
            'param': re.compile(r'@param(?:\[([^\]]+)\])?\s+(\w+)\s+(.+?)(?=@|\n\n|\*/|\Z)', re.DOTALL),
            'tparam': re.compile(r'@tparam\s+(\w+)\s+(.+?)(?=@|\n|\*/|\Z)', re.DOTALL),
            'return': re.compile(r'@return\s+(.+?)(?=@|\n\n|\*/|\Z)', re.DOTALL),
            'retval': re.compile(r'@retval\s+(\w+)\s+(.+?)(?=@|\n|\*/|\Z)', re.DOTALL),
            'throw': re.compile(r'@throws?\s+(.+?)(?=@|\n|\*/|\Z)', re.DOTALL),
            'example': re.compile(r'@example\s+(.+?)(?=@|\n\n|\*/|\Z)', re.DOTALL),
            'code': re.compile(r'@code\s*(.*?)@endcode', re.DOTALL | re.IGNORECASE),
            'note': re.compile(r'@note\s+(.+?)(?=@|\n\n|\*/|\Z)', re.DOTALL),
            'warning': re.compile(r'@warning\s+(.+?)(?=@|\n\n|\*/|\Z)', re.DOTALL),
            'see': re.compile(r'@(?:see|sa)\s+(.+?)(?=@|\n|\*/|\Z)', re.DOTALL),
            'since': re.compile(r'@since\s+(.+?)(?=@|\n|\*/|\Z)', re.DOTALL),
            'deprecated': re.compile(r'@deprecated\s+(.+?)(?=@|\n\n|\*/|\Z)', re.DOTALL),
            'author': re.compile(r'@author\s+(.+?)(?=@|\n|\*/|\Z)', re.DOTALL),
            'date': re.compile(r'@date\s+(.+?)(?=@|\n|\*/|\Z)', re.DOTALL),
            'complexity': re.compile(r'@complexity\s+(.+?)(?=@|\n|\*/|\Z)', re.DOTALL),
            'threadsafe': re.compile(r'@threadsafe', re.IGNORECASE),
            'notthreadsafe': re.compile(r'@notthreadsafe', re.IGNORECASE),
        }
    
    def parse(self, comment_text: str, signature: ElementSignature) -> DocComment:
        """Parse un commentaire Doxygen"""
        
        doc = DocComment(signature=signature)
        
        # @brief
        match = self.tag_patterns['brief'].search(comment_text)
        if match:
            doc.brief = self._clean_text(match.group(1))
        
        # Si pas de @brief, utiliser première ligne
        if not doc.brief:
            lines = comment_text.split('\n')
            for line in lines:
                clean = self._clean_text(line)
                if clean and not clean.startswith('@'):
                    doc.brief = clean
                    break
        
        # @param
        for match in re.finditer(self.tag_patterns['param'], comment_text):
            direction = match.group(1) or "in"
            param_name = match.group(2)
            param_desc = self._clean_text(match.group(3))
            doc.param_docs[param_name] = param_desc
            for param in signature.parameters:
                if param.name == param_name:
                    param.description = param_desc
                    param.direction = direction
        
        # @return
        match = self.tag_patterns['return'].search(comment_text)
        if match:
            doc.returns = self._clean_text(match.group(1))
        
        # @retval
        for match in re.finditer(self.tag_patterns['retval'], comment_text):
            value = match.group(1)
            desc = self._clean_text(match.group(2))
            doc.return_values[value] = desc
        
        # @throw/@throws
        for match in re.finditer(self.tag_patterns['throw'], comment_text):
            doc.throws.append(self._clean_text(match.group(1)))
        
        # @code...@endcode
        for match in re.finditer(self.tag_patterns['code'], comment_text):
            doc.examples.append(match.group(1).strip())
        
        # @note
        for match in re.finditer(self.tag_patterns['note'], comment_text):
            doc.notes.append(self._clean_text(match.group(1)))
        
        # @warning
        for match in re.finditer(self.tag_patterns['warning'], comment_text):
            doc.warnings.append(self._clean_text(match.group(1)))
        
        # @see
        for match in re.finditer(self.tag_patterns['see'], comment_text):
            doc.see_also.append(self._clean_text(match.group(1)))
        
        # Métadonnées
        for tag in ['since', 'deprecated', 'author', 'date', 'complexity']:
            match = self.tag_patterns[tag].search(comment_text)
            if match:
                setattr(doc, tag, self._clean_text(match.group(1)))
        
        # Thread safety
        if self.tag_patterns['threadsafe'].search(comment_text):
            doc.thread_safety = "Thread-safe"
        elif self.tag_patterns['notthreadsafe'].search(comment_text):
            doc.thread_safety = "Not thread-safe"
        
        # Description (tout sauf les tags)
        desc_lines = []
        in_tag = False
        for line in comment_text.split('\n'):
            clean = self._clean_text(line)
            if clean.startswith('@'):
                in_tag = True
                continue
            if not in_tag and clean and clean != doc.brief:
                desc_lines.append(clean)
        if desc_lines:
            doc.description = ' '.join(desc_lines)
        
        return doc
    
    def _clean_text(self, text: str) -> str:
        text = re.sub(r'^\s*\*+\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*/+\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()


# ============================================================================
# UTILITAIRES
# ============================================================================

def create_element_id(element: DocComment) -> str:
    sig = element.signature
    parts = []
    if sig.namespace:
        parts.append(sig.namespace.replace('::', '-').lower())
    if sig.parent_class:
        parts.append(sig.parent_class.replace('::', '-').lower())
    parts.append(sig.name.lower())
    return '-'.join(parts)


def sanitize_filename(name: str) -> str:
    name = name.replace('::', '_')
    name = name.replace('/', '_')
    name = name.replace('\\', '_')
    name = name.replace(' ', '_')
    name = re.sub(r'[<>:"|?*]', '', name)
    return name


# ============================================================================
# GÉNÉRATEUR MARKDOWN
# ============================================================================

class MarkdownGenerator:
    """Générateur de documentation Markdown avec design moderne"""
    
    def __init__(self, project_doc: ProjectDocumentation):
        self.project_doc = project_doc
        self.output_dir = Path(".")
        self.type_icons = {
            ElementType.CLASS: "🏛️",
            ElementType.STRUCT: "🏗️",
            ElementType.ENUM: "🔢",
            ElementType.UNION: "🤝",
            ElementType.FUNCTION: "⚙️",
            ElementType.METHOD: "🔧",
            ElementType.VARIABLE: "📦",
            ElementType.MACRO: "🔣",
            ElementType.TYPEDEF: "📝",
            ElementType.NAMESPACE: "🗂️",
        }
    
    def generate(self, output_dir: Path):
        self.output_dir = output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        print(f"📝 Generating Markdown documentation in: {output_dir}")
        self._generate_index()
        self._generate_by_files()
        self._generate_by_namespace()
        self._generate_by_type()
        self._generate_search()
        self._generate_api()
        self._generate_stats()
        print(f"✅ Markdown generation complete!")
    
    def _generate_index(self):
        stats = self.project_doc.stats
        md = f"""# {self.project_doc.project_name} - Documentation API

> 🚀 Généré le {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

![Elements](https://img.shields.io/badge/Elements-{stats.get('total_elements', 0)}-blue)
![Files](https://img.shields.io/badge/Files-{stats.get('total_files', 0)}-green)
![Coverage](https://img.shields.io/badge/Coverage-{stats.get('documentation_coverage', 0):.0f}%25-orange)

## 📊 Statistiques Rapides

| Catégorie | Nombre |
|-----------|--------|
| 📁 Fichiers | {stats.get('total_files', 0)} |
| 🧩 Éléments | {stats.get('total_elements', 0)} |
| 🏛️ Classes | {stats.get('classes', 0)} |
| 🏗️ Structures | {stats.get('structs', 0)} |
| 🔢 Enums | {stats.get('enums', 0)} |
| ⚙️ Fonctions | {stats.get('functions', 0)} |
| 🔧 Méthodes | {stats.get('methods', 0)} |

## 🔍 Navigation

- [📁 Par Fichier](./files/index.md) - Documentation organisée par fichier source
- [🗂️ Par Namespace](./namespaces/index.md) - Navigation par espace de noms
- [🎯 Par Type](./types/index.md) - Éléments groupés par type
- [🔍 Recherche](./search.md) - Index alphabétique complet
- [🔧 API Complète](./api.md) - Vue d'ensemble de l'API
- [📊 Statistiques](./stats.md) - Métriques détaillées

## 📚 À Propos

Cette documentation a été générée automatiquement depuis les commentaires Doxygen du code source.

**Couverture:** {stats.get('well_documented', 0)} éléments sur {stats.get('total_elements', 0)} ont une documentation complète ({stats.get('documentation_coverage', 0):.1f}%)

---

*Documentation générée avec ❤️ par Jenga Build System*
"""
        (self.output_dir / "index.md").write_text(md, encoding='utf-8')
        print(f"  ✓ index.md")
    
    def _generate_by_files(self):
        files_dir = self.output_dir / "files"
        files_dir.mkdir(exist_ok=True)
        md = f"""# 📁 Documentation par Fichier

> {len(self.project_doc.files)} fichiers documentés

[🏠 Accueil](../index.md)

## Liste des Fichiers

"""
        for file_doc in sorted(self.project_doc.files, key=lambda f: f.file_name):
            md_name = sanitize_filename(file_doc.file_name) + ".md"
            md += f"- 📄 [{file_doc.file_name}](./{md_name}) ({len(file_doc.elements)} éléments)\n"
            self._generate_file_page(file_doc, files_dir)
        (files_dir / "index.md").write_text(md, encoding='utf-8')
        print(f"  ✓ files/ ({len(self.project_doc.files)} files)")
    
    def _generate_file_page(self, file_doc: FileDocumentation, files_dir: Path):
        md_name = sanitize_filename(file_doc.file_name) + ".md"
        md = f"""# 📄 {file_doc.file_name}

[🏠 Accueil](../index.md) | [📁 Fichiers](./index.md)

## Informations

"""
        if file_doc.file_description:
            md += f"**Description:** {file_doc.file_description}\n\n"
        if file_doc.file_author:
            md += f"**Auteur:** {file_doc.file_author}\n\n"
        md += f"**Chemin:** `{file_doc.relative_path}`\n\n"
        if file_doc.includes:
            md += "### 📦 Fichiers Inclus\n\n"
            for inc in file_doc.includes:
                inc_name = Path(inc).name
                linked = False
                for f in self.project_doc.files:
                    if f.file_name == inc_name:
                        inc_md = sanitize_filename(inc_name) + ".md"
                        md += f"- [`{inc}`](./{inc_md})\n"
                        linked = True
                        break
                if not linked:
                    md += f"- `{inc}`\n"
            md += "\n"
        if file_doc.included_by:
            md += "### 🔗 Inclus Par\n\n"
            for inc_by in file_doc.included_by:
                inc_name = Path(inc_by).name
                inc_md = sanitize_filename(inc_name) + ".md"
                md += f"- [`{inc_name}`](./{inc_md})\n"
            md += "\n"
        if file_doc.namespaces:
            md += "### 🗂️ Namespaces\n\n"
            for ns in file_doc.namespaces:
                ns_md = ns.replace('::', '_') + ".md"
                md += f"- [`{ns}`](../namespaces/{ns_md})\n"
            md += "\n"
        md += f"## 🎯 Éléments ({len(file_doc.elements)})\n\n"
        by_type = {}
        for elem in file_doc.elements:
            t = elem.signature.element_type
            if t not in by_type:
                by_type[t] = []
            by_type[t].append(elem)
        for elem_type in sorted(by_type.keys(), key=lambda t: t.value):
            elements = by_type[elem_type]
            icon = self.type_icons.get(elem_type, "📌")
            md += f"### {icon} {elem_type.value.capitalize()}s ({len(elements)})\n\n"
            for elem in sorted(elements, key=lambda e: e.signature.name):
                md += self._format_element(elem, file_doc.file_name)
                md += "\n---\n\n"
        (files_dir / md_name).write_text(md, encoding='utf-8')
    
    def _format_element(self, elem: DocComment, current_file: str = "") -> str:
        sig = elem.signature
        icon = self.type_icons.get(sig.element_type, "📌")
        elem_id = create_element_id(elem)
        md = f'<a name="{elem_id}"></a>\n\n'
        md += f"#### {icon} `{sig.name}`\n\n"
        badges = []
        if sig.is_static:
            badges.append("`static`")
        if sig.is_const:
            badges.append("`const`")
        if sig.is_virtual:
            badges.append("`virtual`")
        if sig.is_constexpr:
            badges.append("`constexpr`")
        if sig.is_noexcept:
            badges.append("`noexcept`")
        if sig.access != "public":
            badges.append(f"`{sig.access}`")
        if badges:
            md += " ".join(badges) + "\n\n"
        md += f"```cpp\n{sig.full_signature}\n```\n\n"
        if elem.brief:
            md += f"**{elem.brief}**\n\n"
        if elem.description:
            md += f"{elem.description}\n\n"
        if sig.template_params:
            md += "**Paramètres Template:**\n\n"
            for tp in sig.template_params:
                md += f"- `{tp}`\n"
            md += "\n"
        if sig.parameters:
            md += "**Paramètres:**\n\n"
            md += "| Nom | Type | Description |\n"
            md += "|-----|------|-------------|\n"
            for param in sig.parameters:
                desc = elem.param_docs.get(param.name, "")
                direction = f"[{param.direction}] " if param.direction else ""
                md += f"| `{param.name}` | `{param.type}` | {direction}{desc} |\n"
            md += "\n"
        if elem.returns:
            md += f"**Retour:** {elem.returns}\n\n"
        if elem.examples:
            md += "**Exemples:**\n\n"
            for i, ex in enumerate(elem.examples, 1):
                md += f"```cpp\n{ex}\n```\n\n"
        for note in elem.notes:
            md += f"> 📝 **Note:** {note}\n\n"
        for warn in elem.warnings:
            md += f"> ⚠️ **Attention:** {warn}\n\n"
        if elem.see_also:
            md += "**Voir Aussi:**\n\n"
            for see in elem.see_also:
                if see in self.project_doc.by_name:
                    target = self.project_doc.by_name[see]
                    target_file = target.file_path
                    target_id = create_element_id(target)
                    if Path(target_file).name == current_file:
                        md += f"- [`{see}`](#{target_id})\n"
                    else:
                        target_md = sanitize_filename(Path(target_file).name) + ".md"
                        md += f"- [`{see}`](./{target_md}#{target_id})\n"
                else:
                    md += f"- `{see}`\n"
            md += "\n"
        meta = []
        if elem.since:
            meta.append(f"Depuis: {elem.since}")
        if elem.complexity:
            meta.append(f"Complexité: {elem.complexity}")
        if elem.thread_safety:
            meta.append(f"Thread-safety: {elem.thread_safety}")
        if meta:
            md += "*" + " | ".join(meta) + "*\n\n"
        if elem.deprecated:
            md += f"> 🚫 **DÉPRÉCIÉ:** {elem.deprecated}\n\n"
        md += f"*Défini dans: `{elem.file_path}:{elem.line_number}`*\n\n"
        return md
    
    def _generate_by_namespace(self):
        ns_dir = self.output_dir / "namespaces"
        ns_dir.mkdir(exist_ok=True)
        md = f"""# 🗂️ Documentation par Namespace

> {len(self.project_doc.by_namespace)} namespaces

[🏠 Accueil](../index.md)

## Liste

"""
        for ns in sorted(self.project_doc.by_namespace.keys()):
            elements = self.project_doc.by_namespace[ns]
            ns_display = "Global" if ns == "__global__" else ns
            ns_md = sanitize_filename(ns) + ".md"
            md += f"- 🗂️ [`{ns_display}`](./{ns_md}) ({len(elements)} éléments)\n"
            self._generate_namespace_page(ns, elements, ns_dir)
        (ns_dir / "index.md").write_text(md, encoding='utf-8')
        print(f"  ✓ namespaces/ ({len(self.project_doc.by_namespace)} namespaces)")
    
    def _generate_namespace_page(self, ns: str, elements: List[DocComment], ns_dir: Path):
        ns_display = "Global" if ns == "__global__" else ns
        ns_md = sanitize_filename(ns) + ".md"
        md = f"""# 🗂️ Namespace `{ns_display}`

> {len(elements)} éléments

[🏠 Accueil](../index.md) | [🗂️ Namespaces](./index.md)

## Éléments

"""
        by_type = {}
        for elem in elements:
            t = elem.signature.element_type
            if t not in by_type:
                by_type[t] = []
            by_type[t].append(elem)
        for elem_type in sorted(by_type.keys(), key=lambda t: t.value):
            elems = by_type[elem_type]
            icon = self.type_icons.get(elem_type, "📌")
            md += f"### {icon} {elem_type.value.capitalize()}s ({len(elems)})\n\n"
            for elem in sorted(elems, key=lambda e: e.signature.name):
                file_name = Path(elem.file_path).name
                file_md = sanitize_filename(file_name) + ".md"
                elem_id = create_element_id(elem)
                md += f"- **[`{elem.signature.name}`](../files/{file_md}#{elem_id})**"
                if elem.brief:
                    md += f" — {elem.brief}"
                md += "\n"
            md += "\n"
        (ns_dir / ns_md).write_text(md, encoding='utf-8')
    
    def _generate_by_type(self):
        types_dir = self.output_dir / "types"
        types_dir.mkdir(exist_ok=True)
        md = """# 🎯 Documentation par Type

[🏠 Accueil](../index.md)

## Types

"""
        type_lists = [
            (ElementType.CLASS, self.project_doc.classes),
            (ElementType.STRUCT, self.project_doc.structs),
            (ElementType.ENUM, self.project_doc.enums),
            (ElementType.UNION, self.project_doc.unions),
            (ElementType.FUNCTION, self.project_doc.functions),
            (ElementType.METHOD, self.project_doc.methods),
            (ElementType.VARIABLE, self.project_doc.variables),
            (ElementType.MACRO, self.project_doc.macros),
            (ElementType.TYPEDEF, self.project_doc.typedefs),
        ]
        for elem_type, elements in type_lists:
            if not elements:
                continue
            icon = self.type_icons.get(elem_type, "📌")
            type_md = elem_type.value + "s.md"
            md += f"- {icon} [{elem_type.value.capitalize()}s](./{type_md}) ({len(elements)} éléments)\n"
            self._generate_type_page(elem_type, elements, types_dir)
        (types_dir / "index.md").write_text(md, encoding='utf-8')
        print(f"  ✓ types/ (9 types)")
    
    def _generate_type_page(self, elem_type: ElementType, elements: List[DocComment], types_dir: Path):
        icon = self.type_icons.get(elem_type, "📌")
        type_md = elem_type.value + "s.md"
        md = f"""# {icon} {elem_type.value.capitalize()}s

> {len(elements)} éléments

[🏠 Accueil](../index.md) | [🎯 Types](./index.md)

## Liste

"""
        for elem in sorted(elements, key=lambda e: e.signature.name):
            file_name = Path(elem.file_path).name
            file_md = sanitize_filename(file_name) + ".md"
            elem_id = create_element_id(elem)
            md += f"- **[`{elem.signature.name}`](../files/{file_md}#{elem_id})**"
            ns = elem.signature.namespace or "__global__"
            if ns != "__global__":
                md += f" (`{ns}`)"
            if elem.brief:
                md += f" — {elem.brief}"
            md += "\n"
        (types_dir / type_md).write_text(md, encoding='utf-8')
    
    def _generate_search(self):
        all_elements = []
        for file_doc in self.project_doc.files:
            all_elements.extend(file_doc.elements)
        md = f"""# 🔍 Recherche Alphabétique

> {len(all_elements)} éléments

[🏠 Accueil](./index.md)

## Index

"""
        by_letter = {}
        for elem in all_elements:
            letter = elem.signature.name[0].upper()
            if letter not in by_letter:
                by_letter[letter] = []
            by_letter[letter].append(elem)
        for letter in sorted(by_letter.keys()):
            md += f"[{letter}](#{letter.lower()}) "
        md += "\n\n---\n\n"
        for letter in sorted(by_letter.keys()):
            md += f'<a name="{letter.lower()}"></a>\n\n'
            md += f"## {letter}\n\n"
            for elem in sorted(by_letter[letter], key=lambda e: e.signature.name.lower()):
                file_name = Path(elem.file_path).name
                file_md = sanitize_filename(file_name) + ".md"
                elem_id = create_element_id(elem)
                icon = self.type_icons.get(elem.signature.element_type, "📌")
                md += f"- {icon} **[`{elem.signature.name}`](./files/{file_md}#{elem_id})**"
                if elem.brief:
                    md += f" — {elem.brief}"
                md += "\n"
            md += "\n"
        (self.output_dir / "search.md").write_text(md, encoding='utf-8')
        print(f"  ✓ search.md")
    
    def _generate_api(self):
        md = f"""# 🔧 API Complète

[🏠 Accueil](./index.md)

## Vue d'Ensemble

Documentation complète de l'API du projet {self.project_doc.project_name}.

"""
        md += "## Par Type\n\n"
        type_lists = [
            (ElementType.CLASS, self.project_doc.classes),
            (ElementType.STRUCT, self.project_doc.structs),
            (ElementType.ENUM, self.project_doc.enums),
            (ElementType.FUNCTION, self.project_doc.functions),
            (ElementType.METHOD, self.project_doc.methods),
        ]
        for elem_type, elements in type_lists:
            if not elements:
                continue
            icon = self.type_icons.get(elem_type, "📌")
            type_md = elem_type.value + "s.md"
            md += f"- {icon} [{elem_type.value.capitalize()}s](./types/{type_md}) ({len(elements)})\n"
        (self.output_dir / "api.md").write_text(md, encoding='utf-8')
        print(f"  ✓ api.md")
    
    def _generate_stats(self):
        stats = self.project_doc.stats
        md = f"""# 📊 Statistiques Détaillées

[🏠 Accueil](./index.md)

## Vue d'Ensemble

| Métrique | Valeur |
|----------|--------|
| Fichiers | {stats.get('total_files', 0)} |
| Éléments | {stats.get('total_elements', 0)} |
| Namespaces | {stats.get('namespaces', 0)} |
| Couverture | {stats.get('documentation_coverage', 0):.1f}% |

## Par Type

| Type | Nombre |
|------|--------|
| 🏛️ Classes | {stats.get('classes', 0)} |
| 🏗️ Structures | {stats.get('structs', 0)} |
| 🔢 Enums | {stats.get('enums', 0)} |
| 🤝 Unions | {stats.get('unions', 0)} |
| ⚙️ Fonctions | {stats.get('functions', 0)} |
| 🔧 Méthodes | {stats.get('methods', 0)} |
| 📦 Variables | {stats.get('variables', 0)} |
| 🔣 Macros | {stats.get('macros', 0)} |
| 📝 Typedefs | {stats.get('typedefs', 0)} |

## Qualité

- **Éléments bien documentés:** {stats.get('well_documented', 0)} / {stats.get('total_elements', 0)}
- **Couverture:** {stats.get('documentation_coverage', 0):.1f}%
- **Paramètres moyens par fonction:** {stats.get('avg_params_per_function', 0):.1f}

"""
        (self.output_dir / "stats.md").write_text(md, encoding='utf-8')
        print(f"  ✓ stats.md")

# ============================================================================
# COMMANDE PRINCIPALE – CLASSE DOCSCOMMAND
# ============================================================================

class DocsCommand:
    """
    jenga docs extract|stats|list|clean [options]
    Génère la documentation des projets.
    """

    @staticmethod
    def Execute(args: List[str]) -> int:
        """Point d'entrée principal de la commande docs."""
        global_parser = argparse.ArgumentParser(add_help=False)
        global_parser.add_argument(
            "--jenga-file",
            help="Path to the workspace .jenga file (default: auto-detected)"
        )

        parser = argparse.ArgumentParser(
            prog="jenga docs",
            description='Génération de documentation pour les projets Jenga',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            parents=[global_parser],
            epilog="""
Exemples:
  jenga docs extract                          # Tous les projets
  jenga docs extract --project NKCore         # Projet spécifique
  jenga docs extract --format markdown        # Format spécifique
  jenga docs extract --include-private        # Inclure membres privés
  jenga docs stats                            # Statistiques
  jenga docs list                             # Lister projets
  jenga docs clean                            # Nettoyer documentation
  
Formats supportés:
  markdown  - Documentation Markdown avec liens fonctionnels (défaut)
  html      - Documentation HTML responsive avec CSS moderne
  pdf       - Documentation PDF professionnelle
  all       - Tous les formats
"""
        )
        
        subparsers = parser.add_subparsers(dest='subcommand', help='Opération de documentation')
        
        # --- Extract ---
        extract_parser = subparsers.add_parser('extract', help='Extraire la documentation depuis les sources')
        extract_parser.add_argument('--project', help='Projet spécifique (défaut: tous)')
        extract_parser.add_argument('--output', default='docs', help='Répertoire de sortie (défaut: docs/)')
        extract_parser.add_argument('--format', choices=['markdown', 'html', 'pdf', 'all'], default='markdown', help='Format de sortie (défaut: markdown)')
        extract_parser.add_argument('--include-private', action='store_true', help='Inclure les membres privés/protégés')
        extract_parser.add_argument('--exclude-projects', nargs='+', help='Projets à exclure')
        extract_parser.add_argument('--exclude-dirs', nargs='+', help='Répertoires à exclure (ex: tests, vendor)')
        extract_parser.add_argument('--verbose', action='store_true', help='Affichage détaillé')
        
        # --- Stats ---
        stats_parser = subparsers.add_parser('stats', help='Afficher les statistiques de documentation')
        stats_parser.add_argument('--project', help='Projet spécifique')
        stats_parser.add_argument('--json', action='store_true', help='Format JSON')
        
        # --- List ---
        list_parser = subparsers.add_parser('list', help='Lister les projets documentables')
        
        # --- Clean ---
        clean_parser = subparsers.add_parser('clean', help='Nettoyer la documentation générée')
        clean_parser.add_argument('--project', help='Projet spécifique')
        clean_parser.add_argument('--output', default='docs', help='Répertoire de sortie (défaut: docs/)')

        if not args:
            parser.print_help()
            return 0

        global_parsed, remaining_args = global_parser.parse_known_args(args)

        try:
            parsed = parser.parse_args(remaining_args)
        except SystemExit as e:
            return int(e.code) if isinstance(e.code, int) else 1

        parsed.jenga_file = global_parsed.jenga_file
        
        if parsed.subcommand == 'extract':
            return DocsCommand._cmd_extract(parsed)
        elif parsed.subcommand == 'stats':
            return DocsCommand._cmd_stats(parsed)
        elif parsed.subcommand == 'list':
            return DocsCommand._cmd_list(parsed)
        elif parsed.subcommand == 'clean':
            return DocsCommand._cmd_clean(parsed)
        elif not parsed.subcommand:
            parser.print_help()
            return 0
        
        return 1

    # -----------------------------------------------------------------------
    # Implémentation des sous-commandes (statiques internes)
    # -----------------------------------------------------------------------

    @staticmethod
    def _load_workspace(parsed):
        """Charge le workspace courant."""
        # Déterminer le répertoire de travail (workspace root)
        workspace_root = Path.cwd()
        if parsed.jenga_file:
            entry_file = Path(parsed.jenga_file).resolve()
            if not entry_file.exists():
                Colored.PrintError(f"Jenga file not found: {entry_file}")
                return 1
        else:
            entry_file = FileSystem.FindWorkspaceEntry(workspace_root)
            if not entry_file:
                Colored.PrintError("No .jenga workspace file found.")
                return 1
        workspace_root = entry_file.parent
        loader = Loader()
        workspace = loader.LoadWorkspace(str(entry_file))
        if not workspace:
            return workspace

        # Normalize workspace location for path comparisons. Some loaders keep
        # "." in workspace.location, which incorrectly marks all projects as
        # external in docs extraction.
        try:
            ws_loc = Path(getattr(workspace, "location", "") or "")
            if not ws_loc.is_absolute():
                ws_loc = (entry_file.parent / ws_loc).resolve()
            workspace.location = ws_loc
        except Exception:
            workspace.location = entry_file.parent.resolve()

        return workspace

    @staticmethod
    def _cmd_extract(args):
        workspace = DocsCommand._load_workspace(args)
        if not workspace:
            Display.Error("Aucun workspace trouvé")
            return 1
        
        Display.Section(f"📚 Documentation - {workspace.name}")
        
        if args.project:
            if args.project not in workspace.projects:
                Display.Error(f"Projet introuvable: {args.project}")
                return 1
            projects = [args.project]
        else:
            projects = list(workspace.projects.keys())
        
        if args.exclude_projects:
            projects = [p for p in projects if p not in args.exclude_projects]
        
        Display.Info(f"📦 {len(projects)} projet(s)")
        print()
        
        stats = {'success': 0, 'failed': 0, 'skipped': 0}
        workspace_dir = Path(workspace.location).resolve()
        
        for project_name in projects:
            project = workspace.projects[project_name]
            project_dir = Path(project.location)
            if not project_dir.is_absolute():
                project_dir = workspace_dir / project_dir
            
            try:
                project_dir.resolve().relative_to(workspace_dir)
            except ValueError:
                Display.Warning(f"⚠️  Externe: {project_name}")
                stats['skipped'] += 1
                continue
            
            result = DocsCommand._extract_project(project_name, project, workspace_dir, args)
            if result:
                stats['success'] += 1
            else:
                stats['failed'] += 1
            print()
        
        DocsCommand._print_summary(stats, args.output)
        return 0 if stats['failed'] == 0 else 1

    @staticmethod
    def _extract_project(name, project, workspace_dir, args):
        Display.Section(f"📦 {name}")
        workspace_dir = Path(workspace_dir)
        
        def get_source_directories(proj, wks_dir):
            dirs = []
            project_dir = Path(proj.location)
            if not project_dir.is_absolute():
                project_dir = wks_dir / project_dir
            for sub in ['src', 'include']:
                d = project_dir / sub
                if d.exists():
                    dirs.append(d)
            if not dirs and project_dir.exists():
                dirs.append(project_dir)
            return dirs
        
        sources = get_source_directories(project, workspace_dir)
        if not sources:
            Display.Warning("  Pas de sources")
            return None
        
        try:
            extractor = DocumentationExtractor(
                project_name=name,
                project_path=workspace_dir / Path(project.location),
                include_private=args.include_private,
                verbose=args.verbose
            )
            
            doc = extractor.extract(sources)
            
            if doc.stats.get('total_elements', 0) == 0:
                Display.warning("  Aucun élément")
                return None
            
            output = workspace_dir / args.output / name
            
            if args.format in ['markdown', 'all']:
                gen = MarkdownGenerator(doc)
                gen.generate(output / 'markdown')
            
            # TODO: HTML, PDF generators
            
            Display.Success(f"  ✓ {doc.stats['total_files']} fichiers")
            Display.Success(f"  ✓ {doc.stats['total_elements']} éléments")
            
            return {'files': doc.stats['total_files'], 'elements': doc.stats['total_elements']}
        except Exception as e:
            Display.Error(f"  ✗ {e}")
            return None

    @staticmethod
    def _print_summary(stats, output):
        Display.Section("📊 RÉSUMÉ")
        Display.Success(f"✓ Succès: {stats['success']}")
        if stats['failed']:
            Display.Error(f"✗ Échecs: {stats['failed']}")
        if stats['skipped']:
            Display.Warning(f"⊘ Ignorés: {stats['skipped']}")
        print()
        Display.Info(f"📂 {output}/")

    @staticmethod
    def _cmd_stats(args):
        workspace = DocsCommand._load_workspace(args)
        if not workspace:
            return 1
        Display.Section("📊 Statistiques")
        Display.Info(f"Projets: {len(workspace.projects)}")
        # TODO: plus de stats
        return 0

    @staticmethod
    def _cmd_list(args):
        workspace = DocsCommand._load_workspace(args)
        if not workspace:
            return 1
        Display.Section("📚 Projets")
        for name in workspace.projects:
            Display.Info(f"📦 {name}")
        return 0

    @staticmethod
    def _cmd_clean(args):
        workspace = DocsCommand._load_workspace(args)
        if not workspace:
            return 1
        output = workspace.location / args.output
        if args.project:
            output = output / args.project
        if output.exists():
            shutil.rmtree(output)
            Display.Success("✓ Nettoyé")
        else:
            Display.Warning("Déjà propre")
        return 0


if __name__ == '__main__':
    docscommand = DocsCommand()
    sys.exit(docscommand.Execute(sys.argv[1:]))
