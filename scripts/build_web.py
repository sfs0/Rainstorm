"""Build a versioned extension into the backed-up Vue deployment.

Original dist files and the rollback snapshot remain untouched. Every bridge
replacement is checked against the known baseline; a different legacy build
must be reviewed before this script can modify it.
"""
from pathlib import Path
import hashlib
import json
import shutil

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'frontend/dist'
EXTENSION = ROOT / 'frontend/extensions'
OUT = ROOT / 'build/web/dist'


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Legacy Vue bridge does not match baseline: ' + old[:100])
    return text.replace(old, new, 1)


def build():
    code = (EXTENSION / 'rain-warning.js').read_text(encoding='utf-8')
    css = (EXTENSION / 'rain-warning.css').read_text(encoding='utf-8')
    version = hashlib.sha256((code + css + Path(__file__).read_text(encoding='utf-8')).encode()).hexdigest()[:12]
    main_name = 'index-rain-' + version + '.js'
    analyse_name = 'analyse-rain-' + version + '.js'
    extension_name = 'rain-warning-' + version + '.js'
    css_name = 'rain-warning-' + version + '.css'
    original_main = 'index-Me4TUIQZ.js'
    original_analyse = 'analyse-IVbRPvcA.js'
    module_names = {path.name: path.stem + '-rw-' + version + '.js' for path in (BASE / 'assets').glob('*.js')}
    module_names[original_main] = main_name
    module_names[original_analyse] = analyse_name

    def rename_modules(source):
        for old, new in module_names.items():
            source = source.replace(old, new)
        return source
    if OUT.exists():
        if not OUT.resolve().is_relative_to((ROOT / 'build').resolve()) or OUT.name != 'dist':
            raise RuntimeError('Refusing to clean an unexpected build path.')
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    shutil.copytree(BASE, OUT, dirs_exist_ok=True)
    for path in (BASE / 'assets').glob('*.js'):
        source = path.read_text(encoding='utf-8')
        if path.name != original_analyse:
            (OUT / 'assets' / module_names[path.name]).write_text(rename_modules(source), encoding='utf-8')
    legacy = (BASE / 'assets' / original_analyse).read_text(encoding='utf-8')
    legacy = rename_modules(legacy)
    legacy = 'import{WarningUpload as RainUpload,WarningResults as RainResults,WarningHistory as RainHistory,activeTool as RainTool}from"./' + extension_name + '";\n' + legacy
    legacy = replace_once(legacy, 'const g=b("segment"),u=b(!1)', 'const g=RainTool,u=b(!1)')
    legacy = replace_once(legacy,
        'style:{flex:1,display:"flex",alignItems:"center",justifyContent:"center"}},[n.imgsrc||r.value?',
        'style:{flex:1,minWidth:0,height:"100%",display:"flex",alignItems:"center",justifyContent:"center"}},[g.value==="rainstorm"?$(RainResults):n.imgsrc||r.value?')
    legacy = replace_once(legacy,
        '$(H,{label:"目标检测",name:"objectDetection"},{default:z(()=>[$(zs,{onImageSelected:j})]),_:1})]),_:1}',
        '$(H,{label:"目标检测",name:"objectDetection"},{default:z(()=>[$(zs,{onImageSelected:j})]),_:1}),$(H,{label:"暴雨预警",name:"rainstorm"},{default:z(()=>[$(RainUpload)]),_:1})]),_:1}')
    legacy = replace_once(legacy, 'd("div",Qs,[ut((I(),L("ul",Gs,', 'd("div",Qs,[$(RainHistory),ut((I(),L("ul",Gs,')
    (OUT / 'assets' / analyse_name).write_text(legacy, encoding='utf-8')
    (OUT / 'assets' / extension_name).write_text(rename_modules(code), encoding='utf-8')
    (OUT / 'assets' / css_name).write_text(css, encoding='utf-8')
    index = (BASE / 'index.html').read_text(encoding='utf-8').replace(original_main, main_name)
    index = index.replace('<title>Vite App</title>', '<title>洪涝灾害监测 · 暴雨预警试用版</title>')
    index = replace_once(index, '</head>', '  <link rel="stylesheet" href="/assets/' + css_name + '">\n</head>')
    (OUT / 'index.html').write_text(index, encoding='utf-8')
    (OUT / 'rain-warning').mkdir(exist_ok=True)
    shutil.copyfile(ROOT / 'warning-service/example.csv', OUT / 'rain-warning/example.csv')
    manifest = {'version': version, 'main': main_name, 'analyse': analyse_name, 'extension': extension_name,
                'module_names': module_names,
                'stylesheet': css_name, 'frontend_files': {p.relative_to(OUT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in OUT.rglob('*') if p.is_file()}}
    (ROOT / 'build/build-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print('Built version', version, 'with', len(manifest['frontend_files']), 'files.')


if __name__ == '__main__':
    build()
