FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

RUN useradd --create-home --uid 10001 runtime

WORKDIR /browser-runtime

RUN python -m pip install --no-cache-dir playwright==1.48.0

COPY runtime_service.py /browser-runtime/runtime_service.py

RUN chown -R runtime:runtime /browser-runtime

USER runtime

ENV BROWSER_RUNTIME_KIND=isolated_browser
ENV BROWSER_RUNTIME_PORT=9222
ENV BROWSER_RUNTIME_PROFILE_ROOT=/tmp/browser-profiles
ENV HOME=/tmp/runtime-home

EXPOSE 9222

HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9222/health', timeout=2).read()"

CMD ["python", "/browser-runtime/runtime_service.py"]
