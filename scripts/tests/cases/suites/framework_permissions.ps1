# Run from an independent PowerShell; no updates or model inference.
$ErrorActionPreference = 'Continue'
whoami /all

foreach ($name in @('llamacpp', 'pi', 'littlecoder', 'ohmypi')) {
    $root = "C:/AI/frameworks/$name"
    $probe = "$root/.permission-probe-$([guid]::NewGuid().ToString('N'))"
    try {
        [System.IO.Directory]::CreateDirectory($probe) | Out-Null
        [System.IO.Directory]::Delete($probe, $false)
        Write-Output "$name PowerShell: OK"
    } catch {
        Write-Output "$name PowerShell: $($_.Exception.Message)"
    }
}

$python = @'
from pathlib import Path
import uuid
for name in ('llamacpp', 'pi', 'littlecoder', 'ohmypi'):
    path = Path('C:/AI/frameworks') / name / ('.permission-probe-' + uuid.uuid4().hex)
    try:
        path.mkdir()
        path.rmdir()
        print(name, 'Python: OK')
    except OSError as error:
        print(name, 'Python:', error)
'@
& C:/AI/.venv/Scripts/python.exe -c $python

$javascript = @'
const fs = require('fs');
const crypto = require('crypto');
for (const name of ['llamacpp', 'pi', 'littlecoder', 'ohmypi']) {
    const path = 'C:/AI/frameworks/' + name + '/.permission-probe-' + crypto.randomUUID();
    try {
        fs.mkdirSync(path);
        fs.rmdirSync(path);
        console.log(name, 'Node: OK');
    } catch (error) {
        console.log(name, 'Node:', error.message);
    }
}
'@
& node -e $javascript
