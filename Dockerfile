FROM debian:trixie

RUN apt-get update
RUN apt-get upgrade -y
RUN apt-get install -y
RUN apt-get install -y python3
RUN apt-get install -y python3-pip
RUN apt-get install -y python3-flask
RUN apt-get install -y python3-pandas
RUN apt-get install -y python3-jinja2
RUN apt-get install -y python3-gunicorn

COPY app /app/
WORKDIR /app/

CMD ["python3", "-m", "gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "app:create_app()"]
