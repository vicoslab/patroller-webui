FROM ubuntu:24.04
LABEL maintainer "Domen Tabernik <domen.tabernik@fri.uni-lj.si>"

RUN apt-get update --fix-missing && \
    apt-get install -y python3-pip && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

ENV PYTHONPATH=/code

ADD patroller_webui /code/patroller_webui
ADD main.sh /code/
ADD setup.py /code/
ADD README.md /code/
ADD requirements.txt /code/

RUN pip3 install -r /code/requirements.txt --break-system-packages
RUN pip3 install /code/. --break-system-packages

RUN chmod +x /code/main.sh

EXPOSE 80

ENTRYPOINT [ "/code/main.sh" ]