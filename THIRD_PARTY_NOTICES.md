# Third-Party Notices

## Inno Setup Chinese Simplified language file

`packaging/ChineseSimplified.isl` is sourced from the official Inno Setup
`issrc` translation resources and is distributed under the terms included in
that file and the Inno Setup license. Source:
https://github.com/jrsoftware/issrc/blob/main/Files/Languages/ChineseSimplified.isl

BNU-ToolBox includes or interacts with third-party software. Their licenses
apply independently of the project's MIT license.

## Python Runtime

The installer bundles the CPython runtime. Python is distributed under the
Python Software Foundation License. The full Python license text is copied to
`runtime/LICENSE.txt` in the installed application.

- Python: <https://www.python.org/>
- License: <https://docs.python.org/3/license.html>

## Microsoft Edge and Edge WebDriver

BNU-ToolBox currently supports Microsoft Edge on Windows 11. The application
does not redistribute `msedge.exe`.

The matching Microsoft Edge WebDriver is downloaded at runtime from Microsoft's
official Edge WebDriver endpoints and stored in the current user's local data
directory. Microsoft's license terms apply to Edge and Edge WebDriver. The
installer does not grant any rights to Microsoft's trademarks or binaries.

- Edge WebDriver: <https://developer.microsoft.com/microsoft-edge/tools/webdriver/>
- Microsoft software license terms apply.

## Python Packages

The bundled Python environment includes open-source packages, including:

- FastAPI — MIT
- Uvicorn — BSD-3-Clause
- Selenium — Apache-2.0
- cryptography — Apache-2.0 / BSD-3-Clause
- requests — Apache-2.0
- python-multipart — Apache-2.0

Transitive dependencies retain their own licenses. Their license files are
included under the bundled `site-packages` directory.

## Web Frontend

- Vue 3.5.43 — MIT
- Element Plus 2.14.6 — MIT
- Element Plus Icons Vue 2.3.2 — MIT

The complete license texts are included in distributed packages under
`app/web/vendor/licenses/`.

## Build Tools

Distributed installers are built with Inno Setup 6.7.3. Inno Setup is
copyrighted by Jordan Russell and Martijn Laan. This edition is designated
for non-commercial use; other uses require appropriate terms from the
Inno Setup licensor. The project's source license does not override the
installer's terms.

- Inno Setup: <https://jrsoftware.org/isinfo.php>
- License: <https://jrsoftware.org/files/is/license.txt>

## Plugins

Plugins are distributed from independent repositories and may use their own
licenses. Installing a plugin does not change the license of its source code.
