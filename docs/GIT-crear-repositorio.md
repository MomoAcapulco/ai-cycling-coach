# Crear el repositorio git

Se hace una sola vez, en tu Mac y con tu identidad de git. El script crea el repositorio **en esta carpeta**
(`ai-cycling-coach-v4.3.0`).

Qué hace y qué no:
- **No sube nada a internet.** Publicarlo es el paso 7, después de limpiar el historial (paso 6).
- **No toca las otras carpetas de versiones.**
- **No mete nada privado:** ni `.env`, ni `diagnostics/`, ni grabaciones, ni `node_modules`. Tus datos viven en
  `ai-cycling-coach-data/`, que está fuera.

## 1. Ve a la carpeta del proyecto

```sh
cd ~/dev/ai-cycling-coach-v4.3.0
```

## 2. Crear el repositorio con el historial

El script importa primero la v4.2.2 desde su carpeta (solo la lee) y encima pone la v4.3.0. Así podrás ver qué
cambió entre las dos.

**Con tu correo personal, solo para este repositorio** (recomendado si tu git global tiene el correo del trabajo).
Tu configuración global no se toca:

```sh
bash scripts/init-git-repo.sh --with-history --email tu-correo-personal@ejemplo.com
```

Si además quieres otro nombre, añade al final `--name "Tu Nombre"`. Si nunca has configurado git en este Mac, el
nombre es obligatorio y el script te lo pedirá.

**Con tu identidad global de git**, tal cual:

```sh
bash scripts/init-git-repo.sh --with-history
```

No hace falta ejecutar `git config` antes: el script configura el correo dentro del repositorio en cuanto lo crea.
Ejecutarlo antes daba el error «not in a git directory», porque el repositorio aún no existía.

Debe terminar con algo así (probado en una copia: unos 125 ficheros y 1,7 MB):

```
Commits of this repository as: Tu Nombre <tu-correo-personal@ejemplo.com>
Committed v4.2.2: 50 files
Committed v4.3.0: 125 files
Check that nothing private went in (should print nothing):
  OK: nothing private
4d1406b (HEAD -> main, tag: v4.3.0) AI Cycling Coach v4.3.0
7bf52e0 (tag: v4.2.2) AI Cycling Coach v4.2.2 (imported from the version folder)
```

## 3. Comprobar

```sh
git status
```

Debe decir `nothing to commit, working tree clean`.

```sh
git diff --stat v4.2.2 v4.3.0
```

Esto lista todo lo que cambió entre las dos versiones.

> **Orden importante:** los pasos 4, 5 y 6 van **antes** de cualquier `git push`. Si subes antes de limpiar el
> historial, tus datos y tu gmail quedan publicados.

## 4. Guardar los últimos cambios

El commit de los filtros de nombre ya lo hiciste. Después llegaron el **enmascarado de datos personales**, los
**pesos de ejemplo** en guías y tests, y la **licencia MIT** (`LICENSE` y `THIRD_PARTY_NOTICES.md`).

Primero comprueba que no queda nada personal. Debe terminar sin listar nada:

```sh
python3 scripts/mask_personal_data.py --check && echo "OK, nada personal"
```

```sh
git add -A && git commit -m "Mask personal data, example weights, MIT license"
```

## 5. Tu correo «noreply» de GitHub

En github.com, con tu **cuenta personal**: **Settings → Emails**.
- Activa **Keep my email addresses private**. Debajo aparece tu dirección, del tipo
  `12345678+tuusuario@users.noreply.github.com`. Cópiala.
- Activa también **Block command line pushes that expose my email**. Así GitHub rechaza cualquier push que lleve
  tu gmail.

## 6. Limpiar el historial antes de publicar (una sola vez)

Los commits que ya tienes incluyen tus datos (la v4.3.0 tenía tu peso en los tests y la v4.2.2, los identificadores
de tus mandos) y tu gmail. Este script deja el historial en **dos commits limpios**:
- `v4.2.2`, enmascarada;
- `v4.3.0`, que es exactamente tu último commit.

Todos quedan con tu correo noreply y conservan las fechas originales. Al final comprueba cada commit. Solo funciona
si aún no has subido nada.

```sh
bash scripts/clean-git-history.sh --email 12345678+tuusuario@users.noreply.github.com
```

Debe terminar con:

```
Clean: two commits, no personal data, every commit as Tu Nombre <12345678+tuusuario@users.noreply.github.com>.
… (HEAD -> main, tag: v4.3.0) AI Cycling Coach v4.3.0
… (tag: v4.2.2) AI Cycling Coach v4.2.2 (imported from the version folder)
```

Si dice `NOT clean`, **no publiques** y pásame lo que sale.

## 7. Publicarlo en GitHub (público)

### 7.1 Que sea tu cuenta PERSONAL

```sh
gh auth status
```

- Si sale tu **cuenta personal**: sigue con el paso 7.2.
- Si sale la **del trabajo**, o «command not found»: entra con la personal. Cuando lo pida, elige
  `GitHub.com` → `HTTPS` → entrar con el navegador, y en el navegador **cambia a tu cuenta personal** antes de
  autorizar.

```sh
gh auth login
```

  Si tienes las dos cuentas, `gh auth switch` cambia entre ellas. Si no tienes `gh`, instálalo con
  `brew install gh` o usa la opción B.

### 7.2 Crear el repositorio y subirlo

En GitHub **no añadas nada** al crearlo: ni README, ni licencia, ni .gitignore. Todo eso ya está en tu repositorio,
y si GitHub creara sus propios ficheros, el primer `push` chocaría con ellos.

**Opción A, con `gh`:**

```sh
gh repo create ai-cycling-coach --public --source . --remote origin --push
```

```sh
git push origin --tags
```

**Opción B, desde la web:**
1. En github.com, con tu cuenta personal: **New repository** → nombre `ai-cycling-coach` → **Public** → todo lo
   demás vacío → **Create repository**.
2. Conecta y sube, cambiando `TU_USUARIO` por tu usuario de GitHub:

```sh
git remote add origin https://github.com/TU_USUARIO/ai-cycling-coach.git
```

```sh
git push -u origin main --tags
```

### 7.2b Si pide usuario y contraseña y «no vale la clave»

GitHub **ya no acepta la contraseña de la cuenta** para `git push`. Hay que darle a git un acceso propio, y lo
más sencillo es que lo gestione `gh`. Solo se hace una vez:

```sh
brew install gh
```

(Si ya lo tienes, salta este paso.)

```sh
gh auth login
```

Responde: `GitHub.com` → `HTTPS` → **Authenticate Git with your GitHub credentials? → Yes** →
`Login with a web browser`. Copia el código que te muestra y, en el navegador, **comprueba que estás en tu cuenta
personal (MomoAcapulco)** antes de autorizar. Si estás en la del trabajo, cierra sesión o cambia de cuenta primero.

```sh
gh auth setup-git
```

Esto hace que git use `gh` para github.com, por delante de una clave antigua que el llavero del Mac pudiera tener
guardada (por ejemplo, la del trabajo).

```sh
gh auth status
```

Debe decir `Logged in to github.com account MomoAcapulco`. Después repite el `push` del paso 7.2:

```sh
git push -u origin main --tags
```

**Si dice `Permission … denied to <otro usuario>`**, git está usando la cuenta del trabajo. Vuelve a ejecutar
`gh auth login` con la cuenta personal y luego `gh auth switch`, y elige MomoAcapulco.

### 7.3 Comprobar

```sh
git status
```

Debe decir `Your branch is up to date with 'origin/main'`. En github.com, el repositorio debe aparecer como
**Public**, con **MIT license** a la derecha y, en «Tags», `v4.2.2` y `v4.3.0`.

## Antes de cada commit a partir de ahora

Si añades grabaciones nuevas a `tests/fixtures` o escribes datos tuyos en una guía, pasa el enmascarador antes:

```sh
python3 scripts/mask_personal_data.py
```

## A partir de ahora

- **Se acabaron las carpetas copiadas por versión.** Se trabaja siempre en esta carpeta. Cada versión es un commit
  con su etiqueta (`v4.3.1`, `v4.4.0`…), y el número sigue en el fichero `VERSION`.
- Si quieres, puedes renombrar la carpeta a `ai-cycling-coach`; no hace falta tocar nada más. **Antes**, mira la
  carpeta `~/dev/ai-cycling-coach/` que ya existe: solo tiene restos de un editor (`backend/.project` y
  `backend/bin/`). Puedes borrarla tú si no la usas.
- Las carpetas `ai-cycling-coach-v4.2.2` y el `.zip` de la v4.3.0 ya están dentro del historial: puedes guardarlos
  como copia o borrarlos cuando quieras.

Cuando lo hayas creado, dímelo: a partir de ahí haré commits pequeños de cada cambio, siempre que tú me lo pidas.
