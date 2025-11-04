FROM python:3.10-slim

WORKDIR /app
COPY user_interface/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY user_interface/*.py ./
COPY user_interface/.streamlit ./.streamlit
COPY user_interface/img ./img
COPY dataformats ./dataformats
CMD ["streamlit", "run", "streamlit_app.py"]
