FROM python:3.13-slim
WORKDIR /proxy
COPY proxy.py ./
USER nobody
EXPOSE 3128
CMD ["python", "proxy.py"]
