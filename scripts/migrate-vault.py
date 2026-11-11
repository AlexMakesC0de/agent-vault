#!/usr/bin/env python3
"""Preview/apply a lossless legacy-project to central-profile migration."""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

import profile_memory as profile
from vault_runtime import configure_io, file_lock

HERE=Path(__file__).resolve().parent
ARCHIVE=Path('docs/knowledge/memory/archive/central-v2')
RECEIPT=Path('docs/knowledge/memory/MIGRATION-v2.json')
TOOLS=['agent-memory.py','project-memory-router.py','vault_runtime.py','profile_memory.py','vault_search.py','vault_doctor.py']


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value);return value


memory=module('migration_engine',HERE/'agent-memory.py')


def digest(content):return hashlib.sha256(content).hexdigest()


def safe(root,relative):
    relative=Path(relative)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Migration paths must stay within their owning store')
    path=root/relative
    current=root
    for part in relative.parts:
        current=current/part
        if current.is_symlink():raise ValueError(f'Inspect symlink before migrating {current}')
    return path


def immutable(path,content):
    if path.exists() and path.read_bytes()!=content:
        raise ValueError(f'Archive collision at {path}; refusing to replace preserved originals')
    if not path.exists():profile.atomic_write(path,content)


def evidence_paths(value):
    if isinstance(value,dict):
        if isinstance(value.get('source'),str):yield value['source'].split('#',1)[0]
        for item in value.values():yield from evidence_paths(item)
    elif isinstance(value,list):
        for item in value:yield from evidence_paths(item)


def migrate(args):
    project=args.project.expanduser().resolve();central=args.profile.expanduser().resolve()
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}',args.id):raise ValueError('Use a stable lowercase project id')
    if project==central or project in central.parents or central in project.parents:
        raise ValueError('Project and central profile must be separate, non-nested stores')
    for root,names in [(project,[profile.PROJECT_STORE,RECEIPT,ARCHIVE,'MEMORY.md','SOUL.md','.memory-runtime/write.lock']),
                       (central,[profile.PROFILE_STORE,'USER.md','MEMORY.md','SOUL.md',f'imports/{args.id}','.memory-runtime/write.lock'])]:
        for name in names:safe(root,name)
    # The lock order is always central first, then project, including recovery.
    with file_lock(central/'.memory-runtime/write.lock'),file_lock(project/'.memory-runtime/write.lock'):
        source=memory.load(project);target=memory.load(central)
        if not profile.is_profile(target):raise ValueError('Destination must be an initialized central profile')
        journal_path=project/RECEIPT
        journal=json.loads(journal_path.read_text(encoding='utf-8')) if journal_path.exists() else None
        before_path=safe(central,f'imports/{args.id}/profile-before.json')
        prior_target=json.loads(before_path.read_text(encoding='utf-8')) if journal and before_path.exists() else None
        imported_target=target.get('imports',{}).get(args.id)
        for role,name in [('user','USER.md'),('memory','MEMORY.md')]:
            current=(central/name).read_text(encoding='utf-8')
            valid=[profile.render(target,role)]
            if prior_target and imported_target and imported_target['source_sha256']==journal['source_sha256']:
                valid.append(profile.render(prior_target,role))
            if current not in valid:
                raise ValueError(f'Central {name} differs from its state; preserve/reconcile manual edits before migration')
        if source['schema']==2:
            migration=source.get('migration')
            if migration and target.get('imports',{}).get(args.id,{}).get('source_sha256')!=migration['source_sha256']:
                raise ValueError('Central profile lacks this project transfer; restore the correct profile first')
            if migration:
                receipt=json.loads((project/RECEIPT).read_text(encoding='utf-8'))
                for record in receipt['originals'].values():
                    if digest(safe(project,record['archive']).read_bytes())!=record['sha256']:
                        raise ValueError('Preserved archive failed verification; recovery required')
                if not args.apply:
                    return {'status':'preview-already-migrated','phase':receipt['phase']}
                soul=project/'SOUL.md'
                if soul.exists():
                    if digest(soul.read_bytes())!=receipt['originals']['SOUL.md']['sha256']:
                        raise ValueError('A new project SOUL appeared after migration; preserve/reconcile it explicitly')
                    soul.unlink()
                receipt['phase']='complete'
                profile.atomic_write(project/RECEIPT,json.dumps(receipt,indent=2,ensure_ascii=False)+'\n')
            return {'status':'already-migrated','project':str(project),'profile':str(central)}
        if source['revision']!=args.expected_project_revision:raise ValueError('Stale project revision; read and reconcile before migration')
        source_bytes=(project/profile.PROJECT_STORE).read_bytes();source_sha=digest(source_bytes)
        journal_path=project/RECEIPT
        journal=json.loads(journal_path.read_text(encoding='utf-8')) if journal_path.exists() else None
        preimages={}
        if journal:
            if journal.get('source_sha256')!=source_sha:raise ValueError('Existing migration journal belongs to different source data')
            for name,record in journal['originals'].items():
                content=safe(project,record['archive']).read_bytes()
                if digest(content)!=record['sha256']:raise ValueError('Migration archive failed verification')
                safe(project,name)
                preimages[name]=content
        def original(name):
            path=safe(project,name)
            if name in preimages:return preimages[name]
            if journal and name in ['MEMORY.md','.gitattributes']:return None
            return path.read_bytes() if path.is_file() else None
        moves={}
        for role,ids in [('user',args.move_user),('memory',args.move_memory)]:
            for key in ids:
                if key in moves and moves[key]!=role:raise ValueError('One entry cannot have two destinations')
                moves[key]=role
        entries={e['id']:e for e in source['entries']}
        if set(moves)-entries.keys():raise ValueError('A selected source entry is missing')
        if any(entries[key]['status']!='active' for key in moves):raise ValueError('Only active entries can be transferred')
        imported=target.get('imports',{}).get(args.id)
        expected_import={'source_sha256':source_sha,'moves':moves}
        if imported and any(imported.get(k)!=v for k,v in expected_import.items()):
            raise ValueError('Import id belongs to a different source or mapping; originals were not changed')
        if not imported and target['revision']!=args.expected_profile_revision:
            raise ValueError('Stale central profile revision; read and reconcile before migration')
        destination=deepcopy(target)
        copied=[]
        for key,role in moves.items():
            entry=deepcopy(entries[key]);entry['id']=args.id+'--'+key;entry['target']=role
            entry['origin']={'project_id':args.id,'entry_id':key,'source_sha256':source_sha,
                             'archive':f'imports/{args.id}/source-state.json'}
            if not imported:
                if any(e['id']==entry['id'] for e in destination['entries']):
                    raise ValueError('Destination entry id collision; refusing to replace existing learning')
                destination['entries'].append(entry)
            copied.append(entry)
        if not imported:
            destination['revision']+=1
            destination.setdefault('imports',{})[args.id]={**expected_import,'archive':f'imports/{args.id}/source-state.json'}
            destination['history'].append({'revision':destination['revision'],'at':memory.now(),'agent':'human',
                                           'action':'import-project','source_sha256':source_sha,'project_id':args.id,
                                           'entries':deepcopy(copied)})
        # Capacity checks happen before any archive or source-file mutation.
        user=profile.render(destination,'user');general=profile.render(destination,'memory')
        revised=deepcopy(source);revised.update(schema=2,scope='project',project=args.name)
        revised['revision']+=1
        changes=[]
        for entry in revised['entries']:
            if entry['id'] in moves:
                before=deepcopy(entry)
                entry['status']='migrated';entry['migrated_to']={'profile':'default','target':moves[entry['id']],
                                                              'id':args.id+'--'+entry['id']}
                changes.append({'before':before,'after':deepcopy(entry)})
        revised['history'].append({'revision':revised['revision'],'at':memory.now(),'agent':'human',
                                    'action':'migrate-central-profile','source_sha256':source_sha,'entries':changes})
        revised['migration']={'id':args.id,'source_sha256':source_sha,'profile':'default','receipt':str(RECEIPT.as_posix())}
        old_soul=original('SOUL.md')
        if old_soul is None:raise ValueError('Legacy project core is missing; recover it before migration')
        legacy_expected=memory.render({**source,'project':source.get('project',args.name)}).replace('\r\n','\n')
        if old_soul.decode('utf-8').replace('\r\n','\n')!=legacy_expected:
            revised['legacy_soul_archive']=(ARCHIVE/'SOUL.md.txt').as_posix()
        project_core=memory.render(revised)
        originals={**preimages,profile.PROJECT_STORE.as_posix():source_bytes,'SOUL.md':old_soul}
        replacements={}
        previous_core=original('MEMORY.md')
        if previous_core is not None:
            originals['MEMORY.md']=previous_core
            revised['previous_memory_archive']=(ARCHIVE/'MEMORY.md.txt').as_posix()
            project_core=memory.render(revised)
        for name in ['AGENTS.md','CLAUDE.md']:
            path=project/name
            content=original(name)
            if content is not None:
                originals[name]=content
                text=content.decode('utf-8').replace('SOUL.md','MEMORY.md')
                text+='\n<!-- BEGIN central-agent-identity -->\n'
                text+='The only agent identity is the machine-selected private central SOUL.md, shared by every coding agent. '
                text+='This repository owns project MEMORY.md and linked knowledge. Load both with the installed '
                text+='`project-memory-router.py context`; project facts do not replace identity or user preferences.\n'
                text+='<!-- END central-agent-identity -->\n'
                replacements[name]=text
        attributes=original('.gitattributes')
        if attributes is not None:originals['.gitattributes']=attributes
        text=attributes.decode('utf-8') if attributes is not None else ''
        patterns=['docs/knowledge/archive/** -text','docs/knowledge/memory/archive/** -text','docs/knowledge/reference/*.md -text']
        text+=('\n' if text and not text.endswith('\n') else '')
        text+=''.join(line+'\n' for line in patterns if line not in text.splitlines())
        replacements['.gitattributes']=text
        # Keep maintained navigation working; immutable imported bodies are deliberately excluded.
        knowledge=project/'docs/knowledge'
        for path in knowledge.rglob('*.md'):
            if 'archive' in path.relative_to(knowledge).parts:continue
            key=path.relative_to(project).as_posix()
            text=original(key).decode('utf-8')
            if '<!-- preserved-source -->' in text:continue
            def link(match):
                href=match.group(1);base=href.split('#',1)[0]
                if not base or '://' in base:return match.group(0)
                if (path.parent/base).resolve()==project/'SOUL.md':return ']('+href.replace('SOUL.md','MEMORY.md')+')'
                return match.group(0)
            changed=re.sub(r'\]\(([^)\s]+)\)',link,text)
            if changed!=text:
                originals[key]=original(key);replacements[key]=changed
        for name in TOOLS:
            key='scripts/'+name;path=project/key;content=(HERE/name).read_bytes()
            prior=original(key)
            if prior is not None and prior!=content:
                if not args.upgrade_tools:raise ValueError('Owned tools differ; review and use --upgrade-tools to preserve/upgrade them')
                originals[key]=prior
            replacements[key]=content
        evidence=set()
        for candidate in evidence_paths(source):
            path=project/candidate
            try:relative=path.resolve().relative_to(project)
            except (ValueError,OSError):continue
            if path.is_file():
                key=relative.as_posix();evidence.add(key)
                originals.setdefault(key,original(key))
        for name,content in originals.items():
            current=(project/name).read_bytes() if (project/name).is_file() else None
            planned=project_core if name=='MEMORY.md' else replacements.get(name,content)
            if isinstance(planned,str):planned=planned.encode('utf-8')
            if current not in [content,planned]:
                raise ValueError(f'{name} changed since the preserved preimage; reconcile before continuing')
        if journal and 'MEMORY.md' not in preimages and (project/'MEMORY.md').exists():
            if (project/'MEMORY.md').read_bytes()!=project_core.encode('utf-8'):
                raise ValueError('New MEMORY.md differs from planned projection; preserve/reconcile before recovery')
        if journal and '.gitattributes' not in preimages and (project/'.gitattributes').exists():
            if (project/'.gitattributes').read_bytes()!=replacements['.gitattributes'].encode('utf-8'):
                raise ValueError('New .gitattributes differs from planned output; preserve/reconcile before recovery')
        records={name:{'sha256':digest(content),'archive':(ARCHIVE/(name+'.txt')).as_posix()}
                 for name,content in originals.items()}
        receipt={'schema':2,'phase':'prepared','project_id':args.id,'source_sha256':source_sha,'source_revision':source['revision'],
                 'profile_revision':destination['revision'],'moves':moves,'originals':records,
                 'source_entries':len(source['entries']),'source_history_records':len(source['history']),
                 'legacy_soul_matches_projection':'legacy_soul_archive' not in revised}
        for name,record in records.items():safe(project,record['archive'])
        for name in replacements:safe(project,name)
        for name in evidence:safe(central,Path(f'imports/{args.id}/evidence')/name)
        if not args.apply:return {**receipt,'status':'preview','project':str(project),'profile':str(central)}
        for name,content in originals.items():immutable(project/records[name]['archive'],content)
        if not imported:immutable(central/f'imports/{args.id}/profile-before.json',(central/profile.PROFILE_STORE).read_bytes())
        immutable(central/f'imports/{args.id}/source-state.json',source_bytes)
        immutable(central/f'imports/{args.id}/source-SOUL.md.txt',old_soul)
        for name,content in originals.items():
            if name in evidence:
                immutable(central/f'imports/{args.id}/evidence'/name,content)
        profile.atomic_write(project/RECEIPT,json.dumps(receipt,indent=2,ensure_ascii=False)+'\n')
        if not imported:
            profile.atomic_write(central/profile.PROFILE_STORE,json.dumps(destination,indent=2,ensure_ascii=False)+'\n')
        profile.atomic_write(central/'USER.md',user);profile.atomic_write(central/'MEMORY.md',general)
        receipt['phase']='destination-committed'
        profile.atomic_write(project/RECEIPT,json.dumps(receipt,indent=2,ensure_ascii=False)+'\n')
        for name,content in replacements.items():profile.atomic_write(project/name,content)
        profile.atomic_write(project/'MEMORY.md',project_core)
        profile.atomic_write(project/profile.PROJECT_STORE,json.dumps(revised,indent=2,ensure_ascii=False)+'\n')
        receipt['phase']='project-committed'
        profile.atomic_write(project/RECEIPT,json.dumps(receipt,indent=2,ensure_ascii=False)+'\n')
        if (project/'SOUL.md').read_bytes()!=old_soul:raise ValueError('Source SOUL changed outside the lock; preserved originals, refusing deletion')
        if any(safe(project,record['archive']).read_bytes()!=originals[name] for name,record in records.items()):
            raise ValueError('Archive verification failed; refusing to remove legacy core')
        (project/'SOUL.md').unlink()
        receipt['phase']='complete'
        profile.atomic_write(project/RECEIPT,json.dumps(receipt,indent=2,ensure_ascii=False)+'\n')
        return {**receipt,'status':'migrated','project':str(project),'profile':str(central)}


def main():
    configure_io();parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True);parser.add_argument('--profile',type=Path,required=True)
    parser.add_argument('--id',required=True);parser.add_argument('--name',required=True)
    parser.add_argument('--move-user',action='append',default=[]);parser.add_argument('--move-memory',action='append',default=[])
    parser.add_argument('--expected-project-revision',type=int,required=True);parser.add_argument('--expected-profile-revision',type=int,required=True)
    parser.add_argument('--upgrade-tools',action='store_true');parser.add_argument('--apply',action='store_true')
    try:print(json.dumps(migrate(parser.parse_args()),ensure_ascii=False));return 0
    except (OSError,ValueError,KeyError,TypeError) as error:print(f'Migration refused: {error}',file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
