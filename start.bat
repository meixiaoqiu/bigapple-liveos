@echo off
setlocal EnableDelayedExpansion

set "APP_DIR=%~dp0"
cd /d "%APP_DIR%"

echo Starting Big Apple Docker development environment...
echo.

echo Checking Docker Desktop / Docker Engine...

docker version >nul 2>nul
if errorlevel 1 (
echo Docker Engine is not ready. Trying to start Docker Desktop...

set "DOCKER_DESKTOP_EXE=C:\Program Files\Docker\Docker\Docker Desktop.exe"

if not exist "!DOCKER_DESKTOP_EXE!" (
    set "DOCKER_DESKTOP_EXE=%LocalAppData%\Docker\Docker Desktop.exe"
)

if not exist "!DOCKER_DESKTOP_EXE!" (
    echo Docker Desktop executable was not found.
    echo Checked:
    echo C:\Program Files\Docker\Docker\Docker Desktop.exe
    echo %LocalAppData%\Docker\Docker Desktop.exe
    set "EXIT_CODE=1"
    goto END
)

echo Starting Docker Desktop:
echo !DOCKER_DESKTOP_EXE!
start "" "!DOCKER_DESKTOP_EXE!"

echo.
echo Waiting for Docker Engine to become ready...

for /L %%I in (1,1,90) do (
    docker version >nul 2>nul
    if not errorlevel 1 (
        echo Docker Engine is ready.
        goto DOCKER_READY
    )

    echo Docker Engine is not ready yet. Retry %%I/90...
    timeout /t 2 /nobreak >nul
)

echo Docker Engine did not become ready in time.
echo Please open Docker Desktop manually and check its status.
set "EXIT_CODE=1"
goto END

) else (
echo Docker Engine is already ready. Skipping Docker Desktop startup.
)

:DOCKER_READY

docker network inspect dev-net >nul 2>nul
if errorlevel 1 (
echo dev-net Docker network was not found.
echo Please create the shared dev-net network first.
set "EXIT_CODE=1"
goto END
)

docker container inspect mysql97 >nul 2>nul
if errorlevel 1 (
echo mysql97 container was not found.
echo Please create the shared mysql97 container first.
set "EXIT_CODE=1"
goto END
)

set "MYSQL_RUNNING="
for /f %%S in ('docker inspect -f "{{.State.Running}}" mysql97 2^>nul') do set "MYSQL_RUNNING=%%S"

if /I not "%MYSQL_RUNNING%"=="true" (
echo mysql97 exists but is not running. Starting mysql97...
docker start mysql97
if errorlevel 1 (
echo Failed to start mysql97.
set "EXIT_CODE=1"
goto END
)
) else (
echo mysql97 is already running. Skipping.
)

docker inspect mysql97 --format "{{json .NetworkSettings.Networks}}" | findstr /C:"dev-net" >nul
if errorlevel 1 (
echo mysql97 is not connected to dev-net. Connecting...
docker network connect dev-net mysql97
if errorlevel 1 (
echo Failed to connect mysql97 to dev-net.
set "EXIT_CODE=1"
goto END
)
) else (
echo mysql97 is already connected to dev-net. Skipping.
)

echo.
echo Waiting for mysql97 health check...

set "MYSQL_HEALTH="
for /L %%I in (1,1,30) do (
for /f %%H in ('docker inspect -f "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}" mysql97 2^>nul') do set "MYSQL_HEALTH=%%H"

if /I "!MYSQL_HEALTH!"=="healthy" (
    echo mysql97 is healthy.
    goto MYSQL_READY
)

if /I "!MYSQL_HEALTH!"=="none" (
    echo mysql97 has no health check. Waiting briefly...
    timeout /t 5 /nobreak >nul
    goto MYSQL_READY
)

echo mysql97 is not ready yet. Current status: !MYSQL_HEALTH!. Retry %%I/30...
timeout /t 2 /nobreak >nul

)

echo mysql97 did not become healthy in time.
set "EXIT_CODE=1"
goto END

:MYSQL_READY

echo.
echo Building Big Apple Django image...

docker compose -f docker-compose.dev.yml build big-apple-admin
if errorlevel 1 (
echo Failed to build Big Apple Django image.
set "EXIT_CODE=1"
goto END
)

echo.
echo Applying database migrations...

echo Migrating admin/control database...
docker compose -f docker-compose.dev.yml run --rm --no-deps big-apple-admin python manage.py migrate --noinput --settings=live_os.settings_admin
if errorlevel 1 (
echo Failed to migrate admin/control database.
set "EXIT_CODE=1"
goto END
)

echo Migrating real world database...
docker compose -f docker-compose.dev.yml run --rm --no-deps big-apple-real python manage.py migrate --noinput --settings=live_os.settings_real
if errorlevel 1 (
echo Failed to migrate real world database.
set "EXIT_CODE=1"
goto END
)

echo Migrating simulation world database...
docker compose -f docker-compose.dev.yml run --rm --no-deps big-apple-sim python manage.py migrate --noinput --settings=live_os.settings_sim
if errorlevel 1 (
echo Failed to migrate simulation world database.
set "EXIT_CODE=1"
goto END
)

echo Database migrations completed.

echo.
echo Starting Big Apple Django site services...

docker compose -f docker-compose.dev.yml up -d --force-recreate big-apple-admin big-apple-real big-apple-sim
if errorlevel 1 (
echo Failed to start Big Apple Django site services.
set "EXIT_CODE=1"
goto END
)

echo.
echo Starting nginx gateway...

docker container inspect nginx >nul 2>nul
if errorlevel 1 (
echo nginx container was not found.
echo Please create the shared nginx container first.
set "EXIT_CODE=1"
goto END
)

docker inspect nginx --format "{{json .NetworkSettings.Networks}}" | findstr /C:"dev-net" >nul
if errorlevel 1 (
echo nginx is not connected to dev-net. Connecting...
docker network connect dev-net nginx
if errorlevel 1 (
echo Failed to connect nginx to dev-net.
set "EXIT_CODE=1"
goto END
)
) else (
echo nginx is already connected to dev-net. Skipping.
)

set "NGINX_RUNNING="
for /f %%S in ('docker inspect -f "{{.State.Running}}" nginx 2^>nul') do set "NGINX_RUNNING=%%S"

if /I not "%NGINX_RUNNING%"=="true" (
echo nginx exists but is not running. Starting nginx...
docker start nginx
if errorlevel 1 (
echo Failed to start nginx.
echo Check nginx logs with:
echo docker logs --tail 80 nginx
set "EXIT_CODE=1"
goto END
)
) else (
echo nginx is already running. Skipping.
)

echo.
echo Checking nginx config...

docker exec nginx nginx -t
if errorlevel 1 (
echo nginx config test failed.
echo Check nginx logs with:
echo docker logs --tail 80 nginx
set "EXIT_CODE=1"
goto END
)

echo.
echo Reloading nginx...

docker exec nginx nginx -s reload
if errorlevel 1 (
echo nginx reload failed.
echo Check nginx logs with:
echo docker logs --tail 80 nginx
set "EXIT_CODE=1"
goto END
)

echo.
echo Big Apple Docker development environment is running.
echo.
echo Direct Django:
echo http://127.0.0.1:20100/admin/
echo http://127.0.0.1:20100/admin/simulation-lab/
echo http://127.0.0.1:20101/observer/
echo http://127.0.0.1:20101/workspace/
echo http://127.0.0.1:20102/observer/
echo http://127.0.0.1:20102/workspace/
echo.
echo Nginx gateway:
echo http://bigadmin.local/admin/
echo http://bigadmin.local/admin/simulation-lab/
echo http://bigreal.local/observer/
echo http://bigreal.local/workspace/
echo http://bigsim.local/observer/
echo http://bigsim.local/workspace/
echo.
echo Useful commands:
echo docker compose -f docker-compose.dev.yml logs -f
echo docker compose -f docker-compose.dev.yml ps
echo docker logs --since 10m nginx
echo docker logs --since 10m nginx 2^>^&1 ^| findstr /i "emerg alert crit error warn female php85 upstream host"
echo.
echo To stop Big Apple Django site services, use Docker Desktop or run:
echo docker compose -f docker-compose.dev.yml down
echo.

set "EXIT_CODE=0"

:END
if "%EXIT_CODE%"=="" set "EXIT_CODE=0"
echo start.bat finished with exit code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
