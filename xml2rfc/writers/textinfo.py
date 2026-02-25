# Copyright The IETF Trust 2024, All Rights Reserved
# -*- coding: utf-8 -*-
from __future__ import unicode_literals, print_function, division

import lxml.etree
import os
import re

import xml2rfc
from xml2rfc import log
from xml2rfc.writers.base import default_options, BaseV3Writer, RfcWriterError
from xml2rfc.util.name import (full_author_name_expansion, ref_author_name_first,
                                ref_author_name_last)

try:
    from xml2rfc import debug
    debug.debug = True
except ImportError:
    pass

# -------------------------------------------------------------------------

seen = set()

UNNUMBERED_CMDS = {
    1: '@unnumbered',
    2: '@unnumberedsec',
    3: '@unnumberedsubsec',
    4: '@unnumberedsubsubsec',
}


class TexinfoWriter(BaseV3Writer):
    """Renders xml2rfc v3 XML as Texinfo (.texi) output."""

    # Elements that were valid in v2 but are deprecated in v3
    deprecated_element_tags = set([
        'list', 'spanx', 'vspace', 'c', 'texttable', 'ttcol',
        'facsimile', 'format', 'preamble', 'postamble',
    ])

    def __init__(self, xmlrfc, quiet=None, options=default_options, date=None):
        super(TexinfoWriter, self).__init__(xmlrfc, quiet=quiet, options=options, date=date)
        self.refname_mapping = self.get_refname_mapping()
        self.part = 'top'
        self.out = []
        self.local_info_files = getattr(options, 'local_info_files', set())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def write(self, filename):
        """Write the document to a Texinfo file."""
        if not self.root.get('prepTime'):
            prep = xml2rfc.PrepToolWriter(
                self.xmlrfc, options=self.options, date=self.options.date,
                liberal=True, keep_pis=[xml2rfc.V3_PI_TARGET])
            tree = prep.prep()
            if tree is None:
                raise RfcWriterError("Prep tool returned no tree")
            self.tree = tree
            self.root = self.tree.getroot()
            self.refname_mapping = self.get_refname_mapping()

        self.out = []
        self.render(self.root)
        text = '\n'.join(self.out)

        if self.errors:
            raise RfcWriterError("Not creating output file due to errors (see above)")

        with open(filename, 'w', encoding='utf-8') as f:
            f.write(text)

        if not self.options.quiet:
            self.log(' Created file %s' % filename)

    def render(self, x):
        """Dispatch rendering to render_<tagname> methods."""
        if x.tag in (lxml.etree.PI, lxml.etree.Comment):
            return ''
        func_name = "render_%s" % (x.tag.lower(),)
        func = getattr(self, func_name, None)
        if func is None:
            func = self.default_renderer
            if x.tag in self.__class__.deprecated_element_tags:
                self.warn(x, "Was asked to render a deprecated element: <%s>" % (x.tag,))
            elif x.tag not in seen:
                self.warn(x, "No renderer for <%s> found" % (x.tag,))
                seen.add(x.tag)
        return func(x)

    def default_renderer(self, x):
        """Render children and inline text for unknown elements."""
        result = []
        if x.text and x.text.strip():
            result.append(self.escape_texi(x.text))
        for c in x.getchildren():
            child_text = self.render(c)
            if child_text:
                result.append(child_text)
            if c.tail and c.tail.strip():
                result.append(self.escape_texi(c.tail))
        return ''.join(result)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def escape_texi(text):
        """Escape characters special to Texinfo."""
        if not text:
            return ''
        text = text.replace('@', '@@')
        text = text.replace('{', '@{')
        text = text.replace('}', '@}')
        return text

    @staticmethod
    def sanitize_node_name(name):
        """Create a valid Texinfo node name (no commas, colons, or quotes)."""
        name = name.replace(',', ' ')
        name = name.replace(':', ' -')
        name = name.replace('"', '')
        name = name.replace("'", '')
        name = re.sub(r'\s+', ' ', name)
        return name.strip()

    def section_node_name(self, x):
        """Generate a unique node name for a section element."""
        pn = x.get('pn', '')
        name_elem = x.find('name')
        title = self._get_text_content(name_elem) if name_elem is not None else ''

        # Use pn + title for uniqueness
        if pn:
            m = re.match(r'section-(\S+)', pn)
            num = m.group(1) if m else ''
            if num:
                return self.sanitize_node_name('%s. %s' % (num, title))
        anchor = x.get('anchor', '')
        if anchor:
            return self.sanitize_node_name('%s (%s)' % (title, anchor))
        return self.sanitize_node_name(title)

    def depth_from_pn(self, pn):
        """Calculate nesting depth from pn attribute. section-1.2.3 -> 3."""
        if not pn:
            return 1
        m = re.match(r'section-[a-zA-Z]?\.?(\S+)', pn)
        if m:
            return m.group(1).count('.') + 1
        return 1

    def unnumbered_cmd(self, depth):
        """Map nesting depth to @unnumbered variant."""
        return UNNUMBERED_CMDS.get(depth, '@unnumberedsubsubsec')

    def _get_text_content(self, elem):
        """Recursively extract plain text from an element (no markup)."""
        if elem is None:
            return ''
        parts = []
        if elem.text:
            parts.append(elem.text)
        for child in elem:
            parts.append(self._get_text_content(child))
            if child.tail:
                parts.append(child.tail)
        return ''.join(parts)

    def _render_inline(self, x):
        """Render an element's text, children (inline), and tail as Texinfo markup."""
        parts = []
        if x.text:
            parts.append(self.escape_texi(x.text))
        for c in x.getchildren():
            child_text = self.render(c)
            if child_text:
                parts.append(child_text)
            if c.tail:
                parts.append(self.escape_texi(c.tail))
        return ''.join(parts)

    def _render_children(self, x):
        """Render all children of an element, appending to self.out."""
        for c in x.getchildren():
            self.render(c)

    def _section_number(self, x):
        """Extract section number from pn attribute."""
        pn = x.get('pn', '')
        m = re.match(r'section-([A-Z]?\d[\d.]*)', pn)
        if m:
            return m.group(1)
        # Appendix
        m = re.match(r'section-(appendix-[A-Z][\d.]*)', pn)
        if m:
            return m.group(1).replace('appendix-', '').replace('.', '.', 1)
        m = re.match(r'section-([A-Z](?:\.\d+)*)', pn)
        if m:
            return m.group(1)
        return ''

    def _collect_sections(self, x):
        """Collect immediate child section elements."""
        return [c for c in x.getchildren() if c.tag == 'section']

    def _all_descendant_sections(self, x):
        """Collect all descendant section elements (for detail menu)."""
        result = []
        for sec in self._collect_sections(x):
            result.append(sec)
            result.extend(self._all_descendant_sections(sec))
        return result

    # ------------------------------------------------------------------
    # Renderers
    # ------------------------------------------------------------------

    def render_rfc(self, x):
        self.part = 'top'
        out = self.out

        title_elem = x.find('./front/title')
        title = self._get_text_content(title_elem) if title_elem is not None else ''
        escaped_title = self.escape_texi(title)

        # --- Preamble ---
        out.append('\\input texinfo')
        out.append('@settitle %s' % escaped_title)
        out.append('@documentencoding UTF-8')
        out.append('@set txicodequoteundirected')
        out.append('@set txicodequotebacktick')
        out.append('')

        # --- Title page ---
        out.append('@titlepage')
        out.append('@title %s' % escaped_title)

        # Document ID (RFC number or draft name)
        rfc_num = x.get('number', '')
        doc_name = x.get('docName', '')
        doc_id = ''
        html_url = ''
        if rfc_num:
            doc_id = 'RFC %s' % rfc_num
            html_url = 'https://datatracker.ietf.org/doc/html/rfc%s' % rfc_num
        elif doc_name:
            doc_id = doc_name
            html_url = 'https://datatracker.ietf.org/doc/html/%s' % doc_name

        # Also check seriesInfo for RFC number
        if not rfc_num:
            for si in x.xpath('./front/seriesInfo'):
                if si.get('name') == 'RFC':
                    rfc_num = si.get('value', '')
                    doc_id = 'RFC %s' % rfc_num
                    html_url = 'https://datatracker.ietf.org/doc/html/rfc%s' % rfc_num
                    break

        if doc_id:
            out.append('@subtitle %s' % self.escape_texi(doc_id))

        # Authors
        for a in x.xpath('./front/author'):
            fullname = a.get('fullname', '')
            if fullname:
                out.append('@author %s' % self.escape_texi(fullname))

        out.append('@end titlepage')
        out.append('')

        # --- Top node ---
        out.append('@node Top')
        out.append('@top %s' % escaped_title)
        out.append('')
        if doc_id:
            out.append('%s: %s' % (self.escape_texi(doc_id), escaped_title))
            out.append('')
        if html_url:
            out.append('HTML: @uref{%s}' % html_url)
            out.append('')

        # Collect top-level sections for menu
        front = x.find('front')
        middle = x.find('middle')
        back = x.find('back')

        abstract = front.find('abstract') if front is not None else None
        top_sections = []
        if middle is not None:
            top_sections.extend(self._collect_sections(middle))
        if back is not None:
            for c in back:
                if c.tag in ('section', 'references'):
                    top_sections.append(c)

        # --- Top-level menu ---
        out.append('@menu')
        if abstract is not None:
            out.append('* Abstract::')
        for sec in top_sections:
            if sec.tag == 'references':
                node_name = self._references_node_name(sec)
            else:
                node_name = self.section_node_name(sec)
            out.append('* %s::' % node_name)
        out.append('@end menu')
        out.append('')

        # --- Detail menu ---
        sections_with_children = []
        for sec in top_sections:
            children = self._collect_sections(sec) if sec.tag == 'section' else []
            if sec.tag == 'references':
                children = [c for c in sec if c.tag == 'references']
            if children:
                sections_with_children.append((sec, children))

        if sections_with_children:
            out.append('@detailmenu')
            out.append(' --- The Detailed Node Listing ---')
            out.append('')
            for sec, children in sections_with_children:
                if sec.tag == 'references':
                    name_elem = sec.find('name')
                    sec_title = self._get_text_content(name_elem) if name_elem is not None else 'References'
                    out.append(self.escape_texi(sec_title))
                else:
                    num = self._section_number(sec)
                    name_elem = sec.find('name')
                    sec_title = self._get_text_content(name_elem) if name_elem is not None else ''
                    if num:
                        out.append('%s. %s' % (self.escape_texi(num), self.escape_texi(sec_title)))
                    else:
                        out.append(self.escape_texi(sec_title))
                out.append('')
                for child in children:
                    if child.tag == 'references':
                        child_node = self._references_node_name(child)
                    else:
                        child_node = self.section_node_name(child)
                    out.append('* %s::' % child_node)
                out.append('')

                # Also list grandchildren for deep navigation
                for child in children:
                    gc = self._collect_sections(child) if child.tag == 'section' else []
                    if gc:
                        if child.tag == 'references':
                            child_title = self._get_text_content(child.find('name')) if child.find('name') is not None else ''
                        else:
                            cn = self._section_number(child)
                            child_name = child.find('name')
                            child_title_text = self._get_text_content(child_name) if child_name is not None else ''
                            child_title = '%s. %s' % (cn, child_title_text) if cn else child_title_text
                        out.append(self.escape_texi(child_title))
                        out.append('')
                        for grandchild in gc:
                            gc_node = self.section_node_name(grandchild)
                            out.append('* %s::' % gc_node)
                        out.append('')

            out.append('@end detailmenu')
            out.append('')

        # --- Abstract ---
        if abstract is not None:
            self.part = 'front'
            self.render(abstract)

        # --- Middle ---
        if middle is not None:
            self.part = 'middle'
            for sec in self._collect_sections(middle):
                self._render_section(sec, 1)

        # --- Back ---
        if back is not None:
            self.part = 'back'
            for c in back:
                if c.tag == 'references':
                    self._render_references_section(c, 1)
                elif c.tag == 'section':
                    self._render_section(c, 1)

        out.append('@bye')
        return ''

    def render_abstract(self, x):
        self.out.append('@node Abstract')
        self.out.append('@unnumbered Abstract')
        self.out.append('')
        for c in x.getchildren():
            self.render(c)
        return ''

    def _render_section(self, x, depth):
        """Render a <section> element with @node and @unnumbered."""
        node_name = self.section_node_name(x)
        self.out.append('@node %s' % node_name)

        cmd = self.unnumbered_cmd(depth)
        num = self._section_number(x)
        name_elem = x.find('name')
        title = self._get_text_content(name_elem) if name_elem is not None else ''

        if num:
            self.out.append('%s %s. %s' % (cmd, self.escape_texi(num), self.escape_texi(title)))
        else:
            self.out.append('%s %s' % (cmd, self.escape_texi(title)))

        # Child sections menu
        child_sections = self._collect_sections(x)
        if child_sections:
            self.out.append('')
            self.out.append('@menu')
            for child in child_sections:
                child_node = self.section_node_name(child)
                self.out.append('* %s::' % child_node)
            self.out.append('@end menu')

        self.out.append('')

        # Render body content (everything except child sections and name)
        for c in x.getchildren():
            if c.tag == 'section':
                continue  # handled below
            if c.tag == 'name':
                continue  # already in heading
            self.render(c)

        # Recurse into child sections
        for child in child_sections:
            self._render_section(child, depth + 1)

    def render_section(self, x):
        """Called via dispatch - determine depth from pn and render."""
        pn = x.get('pn', '')
        depth = self.depth_from_pn(pn)
        self._render_section(x, depth)
        return ''

    # --- References ---

    def _references_node_name(self, x):
        """Generate node name for a <references> element."""
        name_elem = x.find('name')
        title = self._get_text_content(name_elem) if name_elem is not None else 'References'
        pn = x.get('pn', '')
        num = ''
        m = re.match(r'section-(\S+)', pn)
        if m:
            num = m.group(1)
        if num:
            return self.sanitize_node_name('%s. %s' % (num, title))
        return self.sanitize_node_name(title)

    def _render_references_section(self, x, depth):
        """Render a <references> element."""
        node_name = self._references_node_name(x)
        self.out.append('@node %s' % node_name)

        cmd = self.unnumbered_cmd(depth)
        name_elem = x.find('name')
        title = self._get_text_content(name_elem) if name_elem is not None else 'References'
        pn = x.get('pn', '')
        num = ''
        m = re.match(r'section-(\S+)', pn)
        if m:
            num = m.group(1)

        if num:
            self.out.append('%s %s. %s' % (cmd, self.escape_texi(num), self.escape_texi(title)))
        else:
            self.out.append('%s %s' % (cmd, self.escape_texi(title)))

        # Sub-references menu
        sub_refs = [c for c in x if c.tag == 'references']
        if sub_refs:
            self.out.append('')
            self.out.append('@menu')
            for sr in sub_refs:
                sr_node = self._references_node_name(sr)
                self.out.append('* %s::' % sr_node)
            self.out.append('@end menu')

        self.out.append('')

        # Render individual references
        for c in x.getchildren():
            if c.tag == 'name':
                continue
            elif c.tag == 'references':
                self._render_references_section(c, depth + 1)
            elif c.tag in ('reference', 'referencegroup'):
                self._render_reference(c)

    def _render_reference(self, x):
        """Render a single <reference> element."""
        anchor = x.get('anchor', '')
        front = x.find('front')
        if front is None:
            self.out.append('[%s]' % self.escape_texi(anchor))
            self.out.append('')
            return

        title_elem = front.find('title')
        title = self._get_text_content(title_elem) if title_elem is not None else ''

        authors = []
        for a in front.findall('author'):
            fullname = a.get('fullname', '')
            if fullname:
                authors.append(fullname)

        series = []
        for si in x.findall('seriesInfo'):
            series.append('%s %s' % (si.get('name', ''), si.get('value', '')))

        # Build reference line
        parts = ['[%s]' % self.escape_texi(anchor)]
        if authors:
            author_str = ', '.join(self.escape_texi(a) for a in authors[:3])
            if len(authors) > 3:
                author_str += ', et al.'
            parts.append(author_str)
        if title:
            parts.append('"%s"' % self.escape_texi(title))
        if series:
            parts.append(', '.join(self.escape_texi(s) for s in series))

        # Check for target URL
        target = x.get('target', '')
        if target:
            parts.append('@uref{%s}' % target)

        self.out.append('  '.join(parts))
        self.out.append('')

    def render_references(self, x):
        """Render references section when called via dispatch."""
        self.part = 'references'
        self._render_references_section(x, 1)
        return ''

    def render_reference(self, x):
        self._render_reference(x)
        return ''

    def render_referencegroup(self, x):
        """Render a reference group (multiple refs under one anchor)."""
        anchor = x.get('anchor', '')
        self.out.append('[%s]' % self.escape_texi(anchor))
        for c in x.getchildren():
            if c.tag == 'reference':
                self._render_reference(c)
        return ''

    # --- Block elements ---

    def render_t(self, x):
        """Render a <t> paragraph element."""
        text = self._render_inline(x)
        if text.strip():
            self.out.append(text.strip())
            self.out.append('')
        return ''

    def render_sourcecode(self, x):
        """Render <sourcecode> as @example block."""
        text = self._get_text_content(x)
        self.out.append('@example')
        self.out.append(self.escape_texi(text.rstrip()))
        self.out.append('@end example')
        self.out.append('')
        return ''

    def render_artwork(self, x):
        """Render <artwork> as @example block."""
        text = self._get_text_content(x)
        if text.strip():
            self.out.append('@example')
            self.out.append(self.escape_texi(text.rstrip()))
            self.out.append('@end example')
            self.out.append('')
        return ''

    def render_figure(self, x):
        """Render <figure> wrapper."""
        name_elem = x.find('name')
        for c in x.getchildren():
            if c.tag == 'name':
                continue
            self.render(c)
        if name_elem is not None:
            fig_title = self._get_text_content(name_elem)
            if fig_title:
                self.out.append('Figure: %s' % self.escape_texi(fig_title))
                self.out.append('')
        return ''

    def render_blockquote(self, x):
        """Render <blockquote> as @quotation."""
        self.out.append('@quotation')
        for c in x.getchildren():
            self.render(c)
        self.out.append('@end quotation')
        self.out.append('')
        return ''

    def render_aside(self, x):
        """Render <aside> as a note."""
        self.out.append('@quotation Note')
        for c in x.getchildren():
            self.render(c)
        self.out.append('@end quotation')
        self.out.append('')
        return ''

    def render_note(self, x):
        """Render <note> sections."""
        name_elem = x.find('name')
        title = self._get_text_content(name_elem) if name_elem is not None else 'Note'
        self.out.append('@quotation %s' % self.escape_texi(title))
        for c in x.getchildren():
            if c.tag == 'name':
                continue
            self.render(c)
        self.out.append('@end quotation')
        self.out.append('')
        return ''

    # --- Lists ---

    def render_ul(self, x):
        """Render <ul> as @itemize."""
        empty = x.get('empty', 'false') == 'true'
        if empty:
            self.out.append('@itemize')
        else:
            self.out.append('@itemize @bullet')
        for c in x.getchildren():
            if c.tag == 'li':
                self.render(c)
        self.out.append('@end itemize')
        self.out.append('')
        return ''

    def render_ol(self, x):
        """Render <ol> as @enumerate."""
        self.out.append('@enumerate')
        for c in x.getchildren():
            if c.tag == 'li':
                self.render(c)
        self.out.append('@end enumerate')
        self.out.append('')
        return ''

    def render_li(self, x):
        """Render <li> as @item."""
        self.out.append('@item')
        # If li contains block elements, render them
        has_blocks = any(c.tag in ('t', 'ol', 'ul', 'dl', 'sourcecode', 'artwork', 'figure', 'table', 'blockquote')
                         for c in x.getchildren())
        if has_blocks:
            for c in x.getchildren():
                self.render(c)
        else:
            text = self._render_inline(x)
            if text.strip():
                self.out.append(text.strip())
                self.out.append('')
        return ''

    def render_dl(self, x):
        """Render <dl> as @table."""
        self.out.append('@table @asis')
        for c in x.getchildren():
            if c.tag in ('dt', 'dd'):
                self.render(c)
        self.out.append('@end table')
        self.out.append('')
        return ''

    def render_dt(self, x):
        """Render <dt> as @item."""
        text = self._render_inline(x)
        self.out.append('@item %s' % text.strip())
        return ''

    def render_dd(self, x):
        """Render <dd> content."""
        has_blocks = any(c.tag in ('t', 'ol', 'ul', 'dl', 'sourcecode', 'artwork', 'figure', 'table')
                         for c in x.getchildren())
        if has_blocks:
            for c in x.getchildren():
                self.render(c)
        else:
            text = self._render_inline(x)
            if text.strip():
                self.out.append(text.strip())
                self.out.append('')
        return ''

    # --- Tables ---

    def render_table(self, x):
        """Render <table> as @multitable."""
        # Collect column info from first row
        rows = list(x.iter('tr'))
        if not rows:
            return ''

        # Determine column count from first row
        first_cells = list(rows[0])
        ncols = len(first_cells)

        if ncols == 0:
            return ''

        # Use fraction-based column widths
        fraction = '%.2f' % (1.0 / ncols) if ncols > 0 else '1.0'
        col_spec = ' '.join(['@columnfractions'] + [fraction] * ncols)
        self.out.append('@multitable %s' % col_spec)

        for row in rows:
            cells = []
            for cell in row:
                cells.append(self._render_inline_from(cell))
            if row.getparent() is not None and row.getparent().tag == 'thead':
                self.out.append('@headitem %s' % ' @tab '.join(cells))
            else:
                self.out.append('@item %s' % ' @tab '.join(cells))
        self.out.append('@end multitable')
        self.out.append('')
        return ''

    def _render_inline_from(self, x):
        """Render an element's content as inline text."""
        parts = []
        if x.text:
            parts.append(self.escape_texi(x.text))
        for c in x.getchildren():
            child_text = self.render(c)
            if child_text:
                parts.append(child_text)
            if c.tail:
                parts.append(self.escape_texi(c.tail))
        return ''.join(parts).strip()

    def render_thead(self, x):
        for c in x.getchildren():
            self.render(c)
        return ''

    def render_tbody(self, x):
        for c in x.getchildren():
            self.render(c)
        return ''

    def render_tfoot(self, x):
        for c in x.getchildren():
            self.render(c)
        return ''

    def render_tr(self, x):
        # Handled by render_table
        return ''

    def render_th(self, x):
        return self._render_inline(x)

    def render_td(self, x):
        return self._render_inline(x)

    # --- Inline elements ---

    def render_xref(self, x):
        """Render <xref> cross-references.

        Handles both internal refs (sections, figures) and bibliographic
        refs (RFC, drafts).  When the xref carries a section= attribute
        the display mirrors the HTML writer's sectionFormat logic:
          "of"    → Section 1.1 of [RFC6749]
          "comma" → [RFC6749], Section 1.1
          "parens"→ [RFC6749] (Section 1.1)
          "bare"  → 1.1
        """
        target = x.get('target', '')
        derived = x.get('derivedContent', '')
        section = x.get('section', '')
        section_fmt = x.get('sectionFormat', 'of')
        derived_link = x.get('derivedLink', '')

        # Content text (user-provided text inside <xref>)
        content = self._render_inline(x)
        display = content if content.strip() else derived

        # Internal reference (anchor in same document)
        target_elem = self.root.xpath('.//*[@anchor="%s"]' % target) if target else []
        if target_elem:
            te = target_elem[0]
            if te.tag == 'section':
                node = self.section_node_name(te)
                if display:
                    return '%s (@ref{%s})' % (display, node)
                return '@ref{%s}' % node
            elif te.tag == 'references':
                node = self._references_node_name(te)
                if display:
                    return '%s (@ref{%s})' % (display, node)
                return '@ref{%s}' % node
            elif te.tag in ('reference', 'referencegroup'):
                # Bibliographic reference — generate external link
                return self._xref_to_bibref(target, display, section,
                                            section_fmt, derived_link)
            else:
                # Reference to non-section element (e.g., table, figure)
                if display:
                    return display
                return derived or ('[%s]' % self.escape_texi(target))

        # Target not found in document — try as external reference
        return self._xref_to_bibref(target, display, section,
                                    section_fmt, derived_link)

    def _section_label(self, section):
        """Return 'Section', 'Appendix', or 'Part' per section string."""
        if not section:
            return 'Section'
        if section[0].isdigit():
            return 'Section'
        if re.match(r'^[A-Z](\.|$)', section):
            return 'Appendix'
        return 'Part'

    def _xref_to_bibref(self, target, display, section, section_fmt,
                        derived_link):
        """Build a Texinfo cross-reference for a bibliographic entry.

        When *section* is present, format the display text to match
        the HTML writer's sectionFormat behaviour and use derivedLink
        (which already contains the fragment) as the URL.
        """
        url = self._bibref_url(target, derived_link)

        # --- No section attribute: simple reference ---
        if not section:
            if url:
                bracket = '[%s]' % self.escape_texi(display) if display else self.escape_texi(target)
                return '@uref{%s, %s}' % (url, bracket)
            if display:
                return '[%s]' % display
            return '[%s]' % self.escape_texi(target)

        # --- Has section attribute: rich display text ---
        label = self._section_label(section)
        sec_ref = '%s %s' % (label, section)
        ref_text = '[%s]' % self.escape_texi(display or target)

        if section_fmt == 'bare':
            # Just the section number, linked
            if url:
                return '@uref{%s, %s}' % (url, section)
            return section
        elif section_fmt == 'comma':
            # [RFC6749], Section 1.1
            if url:
                return '@uref{%s, %s, %s}' % (
                    self._bibref_url(target, None) or url,
                    ref_text, sec_ref)
                # Can't do two separate links in Texinfo easily;
                # combine into one
            combined = '%s, %s' % (ref_text, sec_ref)
            if url:
                return '@uref{%s, %s}' % (url, combined)
            return combined
        elif section_fmt == 'parens':
            # [RFC6749] (Section 1.1)
            combined = '%s (%s)' % (ref_text, sec_ref)
            if url:
                return '@uref{%s, %s}' % (url, combined)
            return combined
        else:
            # 'of' (default): Section 1.1 of [RFC6749]
            combined = '%s of %s' % (sec_ref, ref_text)
            if url:
                return '@uref{%s, %s}' % (url, combined)
            return combined

    def _bibref_url(self, target, derived_link):
        """Return the best URL for a bibliographic target.

        Uses derivedLink when available (it already includes
        the #section fragment).  Falls back to constructing
        a datatracker URL from the target name.
        """
        if derived_link:
            return derived_link

        rfc_match = re.match(r'^RFC(\d+)$', target)
        if rfc_match:
            return 'https://www.rfc-editor.org/rfc/rfc%s' % rfc_match.group(1)

        draft_match = re.match(r'^(I-D\..+|draft-.+)$', target)
        if draft_match:
            name = target.replace('I-D.', 'draft-')
            return 'https://datatracker.ietf.org/doc/html/%s' % name

        return ''

    def render_eref(self, x):
        """Render <eref> external URL references."""
        target = x.get('target', '')
        content = self._render_inline(x)
        if content.strip():
            return '@uref{%s, %s}' % (target, content.strip())
        return '@uref{%s}' % target

    def render_relref(self, x):
        """Render <relref> (deprecated, converted to xref by preptool)."""
        return self.render_xref(x)

    def render_em(self, x):
        text = self._render_inline(x)
        return '@emph{%s}' % text

    def render_strong(self, x):
        text = self._render_inline(x)
        return '@strong{%s}' % text

    def render_tt(self, x):
        text = self._render_inline(x)
        return '@code{%s}' % text

    def render_bcp14(self, x):
        text = self._render_inline(x)
        return '@strong{%s}' % text

    def render_sub(self, x):
        text = self._render_inline(x)
        return '_%s' % text

    def render_sup(self, x):
        text = self._render_inline(x)
        return '^%s' % text

    def render_br(self, x):
        return '\n'

    def render_spanx(self, x):
        """Render v2 <spanx> (deprecated)."""
        style = x.get('style', 'emph')
        text = self._render_inline(x)
        if style == 'verb':
            return '@code{%s}' % text
        elif style == 'strong':
            return '@strong{%s}' % text
        return '@emph{%s}' % text

    def render_cref(self, x):
        """Render <cref> comment reference."""
        text = self._render_inline(x)
        return '[Comment: %s]' % text

    def render_iref(self, x):
        """Render <iref> index entry."""
        item = x.get('item', '')
        subitem = x.get('subitem', '')
        if subitem:
            return '@cindex %s, %s\n' % (self.escape_texi(item), self.escape_texi(subitem))
        if item:
            return '@cindex %s\n' % self.escape_texi(item)
        return ''

    def render_u(self, x):
        """Render <u> unicode element."""
        return self._render_inline(x)

    def render_contact(self, x):
        """Render <contact> element."""
        fullname = x.get('fullname', '')
        return self.escape_texi(fullname)

    # --- Structural elements that just pass through ---

    def render_front(self, x):
        # Handled by render_rfc
        return ''

    def render_middle(self, x):
        # Handled by render_rfc
        return ''

    def render_back(self, x):
        # Handled by render_rfc
        return ''

    def render_name(self, x):
        # Handled by section rendering
        return ''

    def render_title(self, x):
        return ''

    def render_seriesinfo(self, x):
        return ''

    def render_author(self, x):
        """Render author in Authors' Addresses section."""
        fullname = x.get('fullname', '')
        org_elem = x.find('organization')
        org = self._get_text_content(org_elem) if org_elem is not None else ''

        parts = []
        if fullname:
            parts.append(self.escape_texi(fullname))
        if org:
            parts.append(self.escape_texi(org))

        addr = x.find('address')
        if addr is not None:
            email = addr.find('email')
            if email is not None:
                email_text = self._get_text_content(email)
                if email_text:
                    parts.append('@email{%s}' % self.escape_texi(email_text))
            uri = addr.find('uri')
            if uri is not None:
                uri_text = self._get_text_content(uri)
                if uri_text:
                    parts.append('@uref{%s}' % uri_text)

        if parts:
            self.out.append('\n'.join(parts))
            self.out.append('')
        return ''

    def render_organization(self, x):
        return ''

    def render_address(self, x):
        return ''

    def render_email(self, x):
        return ''

    def render_uri(self, x):
        return ''

    def render_postal(self, x):
        return ''

    def render_phone(self, x):
        return ''

    def render_street(self, x):
        return ''

    def render_city(self, x):
        return ''

    def render_region(self, x):
        return ''

    def render_code(self, x):
        return ''

    def render_country(self, x):
        return ''

    def render_area(self, x):
        return ''

    def render_workgroup(self, x):
        return ''

    def render_keyword(self, x):
        return ''

    def render_date(self, x):
        return ''

    def render_abstract(self, x):
        self.out.append('@node Abstract')
        self.out.append('@unnumbered Abstract')
        self.out.append('')
        for c in x.getchildren():
            self.render(c)
        return ''

    def render_boilerplate(self, x):
        """Skip boilerplate (status of memo, copyright)."""
        return ''

    def render_toc(self, x):
        """Skip table of contents (Info has its own navigation)."""
        return ''

    def render_displayreference(self, x):
        return ''

    def render_annotation(self, x):
        """Render <annotation> inline."""
        text = self._render_inline(x)
        if text.strip():
            return ' (%s)' % text.strip()
        return ''

    def render_refcontent(self, x):
        """Render <refcontent> inline."""
        return self._render_inline(x)

    def render_xi_include(self, x):
        return ''
