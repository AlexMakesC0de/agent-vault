#!/usr/bin/env python3
"""Write a read-only HTML page of your profile, project vaults, people notes and recent memory changes."""
import sys

if sys.version_info < (3, 11):
    raise SystemExit('Agent Vault needs Python 3.11 or newer')

import argparse
import base64
from datetime import datetime, timezone
from html import escape
import importlib.util
import json
from pathlib import Path
import re
import webbrowser

from profile_memory import LIMITS, atomic_write
from vault_runtime import configure_io

HERE = Path(__file__).resolve().parent
# One printing ink per project vault, cycling after eight, as in the design system's group inks.
INKS = [f'var(--ink-{n})' for n in range(1, 9)]
THEMES = [('system', 'System'), ('light', 'Light'), ('dark', 'Dark')]
FIELDS = ['Role', 'Organisation', 'Relationship to me', 'Work contact', 'How to write to them', 'Projects']
SECTIONS = [('profile', 'Profile'), ('projects', 'Projects'), ('people', 'People'), ('changes', 'Recent changes')]
# The page holds private notes, so it may load nothing from the network and send nothing anywhere.
CSP = "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:"
# An open book with a ribbon bookmark, inline because the page fetches nothing.
FAVICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" fill="#F2EFE6"/>'
           '<path d="M16 9.5C13 7.5 8.5 7 4 7.5v17c4.5-.5 9 0 12 2 3-2 7.5-2.5 12-2v-17c-4.5-.5-9 0-12 2z" '
           'fill="#FAF8F2" stroke="#17150F" stroke-width="2" stroke-linejoin="round"/>'
           '<path d="M16 9.5v17" stroke="#17150F" stroke-width="2"/>'
           '<path d="M20 8.2V17l2.2-1.8 2.2 1.8V7.7" fill="#B4471C"/></svg>')

STYLE = """
/* light-dark() follows color-scheme: the OS setting by default, or the reader's choice from the theme toggle. */
:root{color-scheme:light dark;
--paper:light-dark(#F2EFE6,#1A1813);--paper-raised:light-dark(#FAF8F2,#23201A);--ink:light-dark(#17150F,#F2EFE6);
--ink-soft:light-dark(#6B6455,#A69E8B);--rule:light-dark(#D8D2C2,#3D382D);
--ink-1:light-dark(#B4471C,#E2805A);--ink-2:light-dark(#2C6551,#6DB396);--ink-3:light-dark(#2B4A87,#88A4E3);
--ink-4:light-dark(#93325A,#D97BA1);--ink-5:light-dark(#5E4491,#A991DB);--ink-6:light-dark(#7C5A10,#CFA54F);
--ink-7:light-dark(#24657F,#68B4D2);--ink-8:light-dark(#7A3A2A,#C9806C);
--serif:"Libre Caslon Display",Georgia,"Times New Roman",serif;
--mono:"Sometype Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
--xs:4px;--sm:8px;--md:16px;--lg:24px;--xl:40px;--xxl:64px;--gutter:24px;--group-ink:var(--ink)}
:root[data-theme="light"]{color-scheme:light}
:root[data-theme="dark"]{color-scheme:dark}
@media (min-width:900px){:root{--gutter:40px}}
html{scroll-behavior:smooth}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
*,*::before,*::after{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:400 13px/1.6 var(--mono);
font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
::selection{background:var(--ink);color:var(--paper)}
:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
.wrap{max-width:1600px;margin:0 auto;padding:0 var(--gutter)}
h1,h2,h3{font-family:var(--serif);font-weight:400;margin:0}
h1{font-size:clamp(2rem,4vw,2.75rem);line-height:1.02;letter-spacing:-0.01em}
h2{font-size:clamp(2rem,3.2vw,2.5rem);line-height:1.05;font-weight:700;color:var(--ink)}
.vault__title{font-size:1.75rem;line-height:1.05;font-weight:700}
.label{margin:0;font-size:11px;font-weight:500;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-soft)}
.masthead{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:var(--lg);
padding:var(--xl) 0 var(--lg)}
.masthead .label{margin-top:var(--sm)}
.tabs{display:flex;flex-wrap:wrap;gap:var(--lg);padding-bottom:12px;border-bottom:1px solid var(--ink)}
.tab{font:400 20px/1 var(--serif);color:var(--ink-soft);text-decoration:none;padding:18px 0 8px;
border-bottom:1px solid transparent}
.tab:hover{color:var(--ink);border-bottom-color:var(--ink)}
section{padding:var(--xl) 0;border-bottom:1px solid var(--ink);scroll-margin-top:var(--md)}
.section__head{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:var(--md);
margin-bottom:var(--lg)}
.sub{margin:var(--xl) 0 var(--md);padding-top:var(--md);border-top:1px solid var(--rule);font-size:12px;color:var(--ink)}
.vault+.vault{margin-top:var(--xl);padding-top:var(--xl);border-top:1px solid var(--rule)}
.meters{display:grid;gap:var(--md);grid-template-columns:repeat(auto-fit,minmax(220px,1fr));margin-bottom:var(--lg)}
.meter__line{display:flex;justify-content:space-between;font-size:12px;letter-spacing:.02em;color:var(--ink-soft)}
.meter__bar{height:6px;border:1px solid var(--ink);background:var(--paper-raised);margin-top:var(--xs)}
.meter__bar span{display:block;height:100%;background:var(--ink)}
.meter--over .meter__bar{border-style:dashed}
.grid{display:grid;grid-template-columns:1fr;gap:var(--lg)}
@media (min-width:760px){.grid{grid-template-columns:repeat(2,1fr)}}
@media (min-width:1200px){.grid{grid-template-columns:repeat(3,1fr)}}
.card{display:flex;flex-direction:column;background:var(--paper-raised);border:1px solid var(--rule)}
.card:hover,.card:focus-within{border-color:var(--ink)}
.card--draft{border-style:dashed;border-color:var(--ink-soft)}
.card__caption{padding:var(--md);display:flex;flex-direction:column;gap:12px;flex:1}
.card__line{display:flex;align-items:baseline;justify-content:space-between;gap:var(--md)}
.card__title{font-size:26px;line-height:1.05;overflow-wrap:anywhere}
.card__desc{margin:0;font-size:12px;line-height:1.35;letter-spacing:.02em;color:var(--ink-soft);text-align:right;
flex:none;max-width:52%;text-wrap:balance}
.card--draft .card__desc{font-size:11px;font-weight:500;letter-spacing:.12em;text-transform:uppercase;color:var(--ink)}
.card__text{margin:0;white-space:pre-wrap;max-width:68ch;overflow-wrap:anywhere}
.card__source{margin:0;font-size:12px;letter-spacing:.02em;color:var(--ink-soft);overflow-wrap:anywhere}
.card__foot{display:flex;align-items:center;justify-content:space-between;gap:var(--md);margin-top:auto;
padding-top:12px;border-top:1px solid var(--rule)}
.card__index{font-size:12px;color:var(--ink-soft)}
.group-mark{display:inline-flex;align-items:center;gap:var(--sm);font-size:11px;font-weight:500;letter-spacing:.12em;
text-transform:uppercase;color:var(--group-ink)}
.group-mark::before{content:"";width:6px;height:6px;background:var(--group-ink);transform:rotate(45deg);flex:none}
.tags{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:var(--md)}
.tag{font:400 12px/1 var(--mono);letter-spacing:.02em;color:var(--ink-soft);background:var(--paper);
border:1px solid var(--rule);padding:7px 10px;overflow-wrap:anywhere}
.masthead .tags{margin:0}
.masthead__tools{display:flex;flex-direction:column;align-items:flex-end;gap:var(--md)}
.themes{display:flex;gap:0}
.chip{font:500 11px/1 var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--ink);background:var(--paper);
border:1px solid var(--ink);border-radius:0;padding:11px 14px;cursor:pointer}
.chip+.chip{border-left:0}
.chip:hover{background:var(--paper-raised)}
.chip[aria-pressed="true"]{background:var(--ink);color:var(--paper)}
.copy{font:500 11px/1 var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--ink);
background:var(--paper-raised);border:1px solid var(--ink);border-radius:0;padding:8px 12px;cursor:pointer;
flex:none;min-width:88px}
.copy:hover{background:var(--paper)}
.copy[data-done="true"]{background:var(--ink);color:var(--paper)}
.artifact{border:1px solid var(--rule);background:var(--paper-raised)}
.artifact summary{display:flex;justify-content:space-between;gap:var(--md);padding:10px var(--md);cursor:pointer;
list-style:none;font-size:11px;font-weight:500;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-soft)}
.artifact summary::-webkit-details-marker{display:none}
.artifact summary:hover{color:var(--ink)}
.artifact[open] summary{border-bottom:1px solid var(--rule)}
.artifact__text{margin:0;padding:var(--md);font:400 13px/1.6 var(--mono);white-space:pre-wrap;max-width:68ch}
.notice{margin:0 0 var(--lg);padding:var(--md);background:var(--paper-raised);border:1px solid var(--ink);
font-size:12px;max-width:100ch}
.notice strong{font-weight:500}
code{font-family:var(--mono);background:var(--paper);border:1px solid var(--rule);padding:2px 6px}
.fields{margin:0;display:grid;grid-template-columns:max-content 1fr;gap:6px var(--md);font-size:12px}
.fields dt{font-size:11px;font-weight:500;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-soft)}
.fields dd{margin:0;overflow-wrap:anywhere}
.blank{margin:0;color:var(--ink-soft);font-style:italic}
.table{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:12px;letter-spacing:.02em}
th{text-align:left;font-size:11px;font-weight:500;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-soft);
padding:0 var(--md) var(--sm) 0;border-bottom:1px solid var(--ink)}
td{padding:var(--sm) var(--md) var(--sm) 0;border-bottom:1px solid var(--rule);vertical-align:top}
.colophon{display:flex;justify-content:space-between;flex-wrap:wrap;gap:var(--md);padding:var(--lg) 0 var(--xl);
font-size:11px;font-weight:500;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-soft)}
"""

# Runs in <head> so a saved theme applies before the first paint, without a flash of the other theme.
EARLY = """try { const t = localStorage.getItem('agent-vault-theme');
if (t === 'light' || t === 'dark') document.documentElement.dataset.theme = t; } catch {}"""

SCRIPT = """
function applyTheme(choice) {
  if (choice === 'light' || choice === 'dark') document.documentElement.dataset.theme = choice;
  else delete document.documentElement.dataset.theme;
  for (const button of document.querySelectorAll('[data-theme-choice]')) {
    button.setAttribute('aria-pressed', String(button.dataset.themeChoice === (choice || 'system')));
  }
}
applyTheme(document.documentElement.dataset.theme);
document.addEventListener('click', async (event) => {
  const theme = event.target.closest('[data-theme-choice]');
  if (theme) {
    applyTheme(theme.dataset.themeChoice);
    try { localStorage.setItem('agent-vault-theme', theme.dataset.themeChoice); } catch {}
    return;
  }
  const button = event.target.closest('[data-copy]');
  if (!button) return;
  try {
    await navigator.clipboard.writeText(button.dataset.copy);
  } catch {
    const area = document.createElement('textarea');
    area.value = button.dataset.copy;
    document.body.append(area);
    area.select();
    document.execCommand('copy');
    area.remove();
  }
  button.dataset.done = 'true';
  button.textContent = 'Copied';
  setTimeout(() => { button.dataset.done = 'false'; button.textContent = 'Copy request'; }, 1400);
});
"""


def e(value):
    return escape(str(value), quote=True)


def engine():
    # agent-memory.py is a script, not a package; load it for its read-only load and sync_conflicts helpers.
    spec = importlib.util.spec_from_file_location('agent_memory', HERE / 'agent-memory.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def measure(render, state, target):
    # render refuses an oversize projection; the page reports that instead of failing.
    try:
        return len(render(state, target))
    except ValueError:
        return None


def changes(store, state):
    for item in state['history']:
        if not isinstance(item, dict):
            continue
        subject = next((v for v in (item.get('after'), item.get('before')) if isinstance(v, dict)), {})
        yield {'at': str(item.get('at', '')), 'store': store, 'revision': item.get('revision', ''),
               'agent': item.get('agent', ''), 'action': item.get('action', ''),
               'entry': subject.get('id', 'SOUL.md' if item.get('action') == 'set-soul' else ''),
               'source': subject.get('source', item.get('source', ''))}


def people(profile_root):
    folder = profile_root / 'notes' / 'people'
    cards = []
    for path in sorted(folder.glob('*.md')) if folder.is_dir() else []:
        if path.name.lower() == 'readme.md' or path.name.startswith('_'):
            continue
        text = path.read_text(encoding='utf-8')
        name = next((line[2:].strip() for line in text.splitlines() if line.startswith('# ')), path.stem)
        fields = dict(re.findall(r'^- \*\*(.+?):\*\*[ \t]*(.*)$', text, re.MULTILINE))
        history = re.findall(r'^- (\d{4}-\d{2}-\d{2}: .+)$', text, re.MULTILINE)
        cards.append({'file': path.name, 'name': name, 'latest': max(history) if history else '',
                      'fields': {k: fields[k].strip() for k in FIELDS if fields.get(k, '').strip()}})
    return cards


def snapshot(config_dir):
    config = config_dir / 'config.json'
    if not config.is_file():
        raise ValueError('No profile is set up on this computer; run project-memory-router.py install --profile PATH first')
    memory = engine()
    root = Path(json.loads(config.read_text(encoding='utf-8'))['profile_root'])
    state = memory.load(root)
    soul = (root / 'SOUL.md').read_text(encoding='utf-8')
    sizes = [('SOUL.md', len(soul), LIMITS['soul']), ('USER.md', measure(memory.render, state, 'user'), LIMITS['user']),
             ('MEMORY.md', measure(memory.render, state, 'memory'), LIMITS['memory'])]
    history = list(changes('Profile', state))
    registry = config_dir / 'projects.json'
    vaults = []
    for project in json.loads(registry.read_text(encoding='utf-8'))['projects'] if registry.is_file() else []:
        item = {'project': project, 'limit': memory.LIMIT}
        try:
            item['state'] = memory.load(Path(project['root']))
            item['conflicts'] = memory.sync_conflicts(Path(project['root']))
        except (OSError, ValueError) as error:
            item['error'] = str(error)
        else:
            item['size'] = measure(memory.render, item['state'], 'memory')
            history += changes(project['name'], item['state'])
        vaults.append(item)
    return {'generated': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
            'profile': {'root': root, 'state': state, 'soul': soul, 'sizes': sizes,
                        'conflicts': memory.sync_conflicts(root)},
            'vaults': vaults, 'people': people(root),
            'history': sorted(history, key=lambda row: row['at'], reverse=True)[:20]}


def meter(name, used, limit):
    over = used is None
    width = 100 if over else min(100, round(used * 100 / limit))
    figure = f'over {limit:,}' if over else f'{used:,} / {limit:,}'
    return (f'<div class="meter{" meter--over" if over else ""}"><div class="meter__line"><span>{e(name)}</span>'
            f'<span>{figure}</span></div><div class="meter__bar"><span style="width:{width}%"></span></div></div>')


def grid(cards, empty):
    return f'<div class="grid">{"".join(cards)}</div>' if cards else f'<p class="blank">{e(empty)}</p>'


def copy(request):
    return f'<button class="copy" type="button" data-copy="{e(request)}">Copy request</button>'


def card(entry, store, revision, ink):
    inferred = entry.get('kind') == 'inferred'
    request = f'In Agent Vault ({store}, revision {revision}), change entry "{entry["id"]}" so it says: '
    return (f'<article class="card{" card--draft" if inferred else ""}" style="--group-ink:{ink}">'
            '<div class="card__caption"><div class="card__line">'
            f'<h3 class="card__title">{e(entry["id"])}</h3>'
            f'<p class="card__desc">{e("Inferred, not loaded" if inferred else entry.get("kind", ""))}</p></div>'
            f'<p class="card__text">{e(entry.get("text", ""))}</p>'
            f'<p class="card__source">Source: {e(entry.get("source", ""))}</p>'
            f'<div class="card__foot"><span class="group-mark">{e(store)}</span>'
            f'<span class="card__index">{e(str(entry.get("updated_at", ""))[:10])}</span>{copy(request)}</div>'
            '</div></article>')


def conflict(copies, root):
    if not copies:
        return ''
    names = ', '.join(f'<code>{e(c.relative_to(root).as_posix())}</code>' for c in copies)
    return ('<div class="notice"><strong>Sync conflict.</strong> Another computer saved this memory at the same time. '
            f'Memory writes are blocked until your agent reconciles it. Copies: {names}</div>')


def profile_section(item):
    state, label = item['state'], 'Profile'
    active = [x for x in state['entries'] if x.get('status') == 'active']
    groups = ''.join(
        f'<p class="label sub">{name}</p>'
        + grid([card(x, label, state['revision'], 'var(--ink)') for x in active if x.get('target', 'memory') == target],
               'No entries yet.')
        for name, target in [('USER.md: your preferences', 'user'), ('MEMORY.md: general lessons', 'memory')])
    return ('<section id="profile"><div class="section__head"><h2>Your profile</h2>'
            f'<span class="label">Revision {e(state["revision"])}</span></div>'
            f'<div class="tags"><span class="tag">Profile: {e(item["root"])}</span></div>'
            + conflict(item['conflicts'], item['root'])
            + '<div class="meters">' + ''.join(meter(*size) for size in item['sizes']) + '</div>'
            + f'<details class="artifact" open><summary><span>SOUL.md: who your agent is</span>'
            f'<span>{len(item["soul"]):,} characters</span></summary>'
            f'<pre class="artifact__text">{e(item["soul"])}</pre></details>' + groups + '</section>')


def vault_block(item, ink):
    project = item['project']
    places = [f'Vault: {project["root"]}'] + [f'Workspace: {w}' for w in project.get('workspaces', [])]
    if 'state' in item:
        places.insert(0, f'Revision {item["state"]["revision"]}')
    head = (f'<div class="vault" style="--group-ink:{ink}"><div class="section__head">'
            f'<h3 class="vault__title">{e(project["name"])}</h3>'
            f'<span class="group-mark">{e(project["id"])}</span></div>'
            '<div class="tags">' + ''.join(f'<span class="tag">{e(p)}</span>' for p in places) + '</div>')
    if 'error' in item:
        return head + f'<p class="notice">This vault cannot be read: {e(item["error"])}</p></div>'
    state = item['state']
    active = [x for x in state['entries'] if x.get('status') == 'active']
    return (head + conflict(item['conflicts'], Path(project['root']))
            + f'<div class="meters">{meter("MEMORY.md", item["size"], item["limit"])}</div>'
            + grid([card(x, project['name'], state['revision'], ink) for x in active], 'No entries yet.') + '</div>')


def person(note):
    fields = ''.join(f'<dt>{e(k)}</dt><dd>{e(v)}</dd>' for k, v in note['fields'].items() if k != 'Role')
    request = f'Update my people note for {note["name"]}: '
    return ('<article class="card"><div class="card__caption"><div class="card__line">'
            f'<h3 class="card__title">{e(note["name"])}</h3>'
            f'<p class="card__desc">{e(note["fields"].get("Role", ""))}</p></div>'
            f'<dl class="fields">{fields}</dl>'
            f'<p class="card__source">{e(note["latest"] or "No history yet.")}</p>'
            f'<div class="card__foot"><span class="card__index">{e(note["file"])}</span>{copy(request)}</div>'
            '</div></article>')


def history_section(rows):
    columns = ['Revision', 'When', 'Store', 'Agent', 'Action', 'Entry', 'Source']
    if not rows:
        return '<section id="changes"><div class="section__head"><h2>Recent changes</h2></div><p class="blank">No changes yet.</p></section>'
    body = ''.join('<tr>' + ''.join(f'<td>{e(v)}</td>' for v in [
        row['revision'], row['at'][:16].replace('T', ' '), row['store'], row['agent'], row['action'], row['entry'],
        row['source']]) + '</tr>' for row in rows)
    return ('<section id="changes"><div class="section__head"><h2>Recent changes</h2>'
            f'<span class="label">Latest {len(rows)}</span></div><div class="table"><table><thead><tr>'
            + ''.join(f'<th>{c}</th>' for c in columns) + f'</tr></thead><tbody>{body}</tbody></table></div></section>')


def page(data):
    vaults = data['vaults']
    counts = [f'Profile revision {data["profile"]["state"]["revision"]}',
              f'{len(vaults)} project vault{"" if len(vaults) == 1 else "s"}', f'{len(data["people"])} people']
    parts = [
        '<header class="masthead"><div><h1>Agent Vault</h1>',
        f'<p class="label">Memory index · read only · {e(data["generated"])}</p></div>',
        '<div class="masthead__tools"><div class="themes" role="group" aria-label="Theme">'
        + ''.join(f'<button class="chip" type="button" data-theme-choice="{k}" aria-pressed="{str(k == "system").lower()}">'
                  f'{v}</button>' for k, v in THEMES) + '</div>'
        '<div class="tags">' + ''.join(f'<span class="tag">{e(c)}</span>' for c in counts) + '</div></div></header>',
        '<nav class="tabs" aria-label="Sections">' + ''.join(f'<a class="tab" href="#{k}">{v}</a>' for k, v in SECTIONS)
        + '</nav>',
        profile_section(data['profile']),
        '<section id="projects"><div class="section__head"><h2>Project vaults</h2>'
        '<span class="label">Shared with everyone who works on the project</span></div>'
        + (''.join(vault_block(v, INKS[i % len(INKS)]) for i, v in enumerate(vaults))
           or '<p class="blank">No project vaults registered.</p>') + '</section>',
        '<section id="people"><div class="section__head"><h2>People</h2>'
        '<span class="label">Private to your profile; never copied into project vaults</span></div>'
        + grid([person(n) for n in data['people']], 'No people notes yet.') + '</section>',
        history_section(data['history']),
        '<footer class="colophon"><span>Generated by Agent Vault view.py</span>'
        '<span>Change memory through your agent; this page never writes</span></footer>']
    return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            f'<meta http-equiv="Content-Security-Policy" content="{CSP}">'
            '<meta name="viewport" content="width=device-width, initial-scale=1"><title>Agent Vault memory</title>'
            '<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,'
            + base64.b64encode(FAVICON.encode('utf-8')).decode('ascii') + '">'
            f'<script>{EARLY}</script>'
            f'<style>{STYLE}</style></head><body><div class="wrap">' + ''.join(parts)
            + f'</div><script>{SCRIPT}</script></body></html>\n')


def destination(value, config_dir, data):
    path = (value.expanduser() if value else config_dir / 'view.html').absolute()
    # The page holds the private profile and people notes; keep it out of every shared vault and project.
    for item in data['vaults']:
        for root in [item['project']['root'], *item['project'].get('workspaces', [])]:
            if path.resolve().is_relative_to(Path(root).resolve()):
                raise ValueError(f'Write the page outside shared vaults and project folders: {path}')
    return path


def main():
    configure_io()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path.home() / '.config/agent-memory',
                        help='Installed router folder with config.json and projects.json')
    parser.add_argument('--output', type=Path, help='HTML file to write; defaults to view.html in the router folder')
    parser.add_argument('--open', action='store_true', help='Open the page in the default browser')
    args = parser.parse_args()
    try:
        data = snapshot(args.config)
        path = destination(args.output, args.config, data)
        atomic_write(path, page(data))
        if args.open:
            webbrowser.open(path.as_uri())
        print(json.dumps({'view': str(path), 'vaults': len(data['vaults']), 'people': len(data['people'])}))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'Agent Vault view: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
