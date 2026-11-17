# SPDX-FileCopyrightText: 2026 Cristiano Carvalho
# SPDX-License-Identifier: Apache-2.0
"""Links in the markdown of descriptions and comments: bare URLs and #123 references made into links before the
markdown is drawn, the links a comment holds, and whether the terminal shows real hyperlinks. Standard library only."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping

# What linkify leaves alone: fenced code, inline code, links and autolinks already written, and HTML tags.
PROTECTED = re.compile(
    r"(?ms)^[ \t]*(```|~~~).*?^[ \t]*\1[^\n]*$"  # a fenced code block
    r"|(`+)(?:(?!\2).)+?\2"  # inline code
    r"|!?\[[^\]\n]*\]\([^)\n]*\)"  # a link or an image
    r"|<https?://[^>\s]+>"  # an autolink
    r"|<[^>\n]+>"  # an HTML tag
)
URL = re.compile(r"https?://[^\s<>()\[\]\"'`]+")
REF = re.compile(r"(?<![\w/&#.-])(?:([A-Za-z0-9][\w.-]*/[\w.-]+))?#(\d+)\b")
TRAILING = ".,;:!?*_~"  # punctuation that ends a sentence, not a URL
LINK = re.compile(r"!?\[([^\]\n]*)\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)|<(https?://[^>\s]+)>")
WEB = ("http://", "https://")  # the only links Morann draws as hyperlinks or opens


CODE = re.compile(r"(?ms)^[ \t]*(```|~~~).*?^[ \t]*\1[^\n]*$|(`+)(?:(?!\2).)+?\2")  # fenced code, inline code
HTML_LINK = re.compile(r"<a\b[^>]*\bhref=\"([^\"]+)\"[^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)
HTML_IMAGE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
LINKED_IMAGE = re.compile(r"\[!\[([^\]\n]*)\]\([^)\n]*\)\]\(([^)\s]+)[^)\n]*\)")  # [![alt](image)](target)
IMAGE = re.compile(r"!\[([^\]\n]*)\]\(([^)\s]+)[^)\n]*\)")
SUMMARY = re.compile(r"<summary>\s*(.*?)\s*</summary>", re.IGNORECASE | re.DOTALL)
FOOTNOTE_DEFINITION = re.compile(r"(?m)^\[\^([^\]\s]+)\]:[ \t]*")
REFUSED = re.compile(r"\[([^\]\n]*)\]\(\s*<?(?:javascript|vbscript|file|data):[^)\n]*\)", re.IGNORECASE)
FOOTNOTE = re.compile(r"\[\^([^\]\s]+)\]")


def prepare(body: str, repo: str, url_for: Callable[[str, int], str]) -> str:
    """A description's or a comment's markdown made ready for the one renderer every surface uses: HTML links and
    images as markdown links, an image as a link named by its alt text (a linked badge as one link), a <summary> in
    bold, footnotes as [1] with their notes kept, and then linkify. Code, fenced or inline, is left exactly as written."""

    def outside_code(text: str) -> str:
        text = HTML_LINK.sub(lambda m: f"[{m[2].strip() or m[1]}]({m[1]})", text)
        text = HTML_IMAGE.sub(html_image, text)
        text = LINKED_IMAGE.sub(lambda m: f"[{image_name(m[1])}]({m[2]})", text)
        text = IMAGE.sub(lambda m: f"[{image_name(m[1])}]({m[2]})", text)
        text = SUMMARY.sub(lambda m: f"**{re.sub(r'<[^>]+>', '', m[1]).strip()}**", text)
        text = REFUSED.sub(lambda m: m[1], text)  # a link markdown will not draw shows as its text, never raw
        text = FOOTNOTE_DEFINITION.sub(lambda m: f"\\[{m[1]}\\] ", text)  # escaped: not a link definition
        return FOOTNOTE.sub(lambda m: f"\\[{m[1]}\\]", text)

    out, at = [], 0
    for code in CODE.finditer(body or ""):
        out.append(outside_code(body[at : code.start()]))
        if re.match(r"[ \t]*(```|~~~)suggestion\b", code.group(0)):  # the forge's suggested change, named as such
            out.append("**Suggested change**\n\n")
        out.append(code.group(0))
        at = code.end()
    out.append(outside_code((body or "")[at:]))
    return linkify("".join(out), repo, url_for)


def image_name(alt: str) -> str:
    return f"image: {alt}" if alt.strip() else "image"


def html_image(found: re.Match[str]) -> str:
    tag = found.group(0)
    source = re.search(r"\bsrc=\"([^\"]+)\"", tag)
    alt = re.search(r"\balt=\"([^\"]*)\"", tag)
    name = image_name(alt[1] if alt else "")
    return f"[{name}]({source[1]})" if source else f"[{name}]"


def linkify(body: str, repo: str, url_for: Callable[[str, int], str]) -> str:
    """The markdown with every bare URL as an autolink and every #N or OWNER/REPO#N as a link to that pull request or
    issue (`url_for(repo, number)` builds it; #N is in `repo`). Code, links and tags already there stay as written."""
    out, at = [], 0
    for kept in PROTECTED.finditer(body):
        out.append(_links_in(body[at : kept.start()], repo, url_for))
        out.append(kept.group(0))
        at = kept.end()
    out.append(_links_in(body[at:], repo, url_for))
    return "".join(out)


def _links_in(text: str, repo: str, url_for: Callable[[str, int], str]) -> str:
    def url(found: re.Match[str]) -> str:
        whole = found.group(0)
        bare = whole.rstrip(TRAILING)
        return f"<{bare}>{whole[len(bare) :]}"

    def ref(found: re.Match[str]) -> str:
        owner_repo, number = found.group(1), int(found.group(2))
        return f"[{found.group(0)}]({url_for(owner_repo or repo, number)})"

    pieces, at = [], 0
    for found in URL.finditer(text):  # URLs first, so a #fragment inside one is not taken for a reference
        pieces.append(REF.sub(ref, text[at : found.start()]))
        pieces.append(url(found))
        at = found.end()
    pieces.append(REF.sub(ref, text[at:]))
    return "".join(pieces)


def links(body: str) -> list[tuple[str, str]]:
    """The (text, URL) of every web link in the markdown, in order, once each; code is skipped."""
    seen, found = set(), []
    for kept in PROTECTED.finditer(body):
        piece = kept.group(0)
        if piece.lstrip().startswith(("```", "~~~", "`")):
            continue
        for link in LINK.finditer(piece):
            text, target = (link.group(1), link.group(2)) if link.group(2) else (link.group(3), link.group(3))
            if target.startswith(WEB) and target not in seen:
                seen.add(target)
                found.append((text or target, target))
    return found


TRUE, FALSE = ("1", "yes", "on", "true"), ("0", "no", "off", "false")
HYPERLINK_TERMS = ("kitty", "foot", "alacritty", "ghostty", "wezterm", "contour", "rio")
HYPERLINK_PROGRAMS = ("iterm.app", "wezterm", "vscode", "ghostty", "hyper", "tabby", "rio", "warpterminal")
HYPERLINK_MARKERS = ("KITTY_WINDOW_ID", "WEZTERM_PANE", "ALACRITTY_WINDOW_ID", "WT_SESSION", "KONSOLE_VERSION")


def hyperlinks(environ: Mapping[str, str]) -> bool:
    """Whether the terminal turns OSC 8 into links you can click: MORANN_HYPERLINKS (1 or 0) says, else a terminal
    known to, outside tmux and screen, which need their own setting to pass them on. Without them a link is its text
    alone; gx shows and opens its address."""
    told = environ.get("MORANN_HYPERLINKS", "").strip().lower()
    if told in TRUE or told in FALSE:
        return told in TRUE
    if environ.get("TMUX") or environ.get("STY"):
        return False
    term, program = environ.get("TERM", "").lower(), environ.get("TERM_PROGRAM", "").lower()
    vte = environ.get("VTE_VERSION", "")
    return (
        any(name in term for name in HYPERLINK_TERMS)
        or program in HYPERLINK_PROGRAMS
        or any(environ.get(marker) for marker in HYPERLINK_MARKERS)
        or vte.isdigit()
        and int(vte) >= 5000
    )
