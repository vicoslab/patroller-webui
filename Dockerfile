FROM nvidia/cuda:10.1-base-ubuntu18.04
LABEL maintainer "Domen Tabernik <domen.tabernik@fri.uni-lj.si>"

RUN apt-get update --fix-missing && \
    apt-get install -y python3-pip && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

ENV PYTHONPATH=/code

ADD patroller_webui /code/patroller_webui
ADD setup.py /code/
ADD README.md /code/
ADD requirements.txt /code/

RUN pip3 install /code/ -r /code/requirements.txt

EXPOSE 80

ENTRYPOINT ["streamlit", "run", "/code/patroller_webui/main.py" ]