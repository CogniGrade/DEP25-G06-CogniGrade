# Cognigrade App - Automated Handwritten Answer Script Grading for Schools & College

## Demo Video

https://github.com/user-attachments/assets/6c9ccf06-23de-4910-9352-0979f76ba63b

See complete video at - [Link](https://drive.google.com/file/d/1WCD6oESae6zC9oE82pmh4F-x6Ft0ZHmp/view?usp=sharing)

## More Details
Techstack - Python FastAPI, SQLite3, JavaScript, HTML, CSS

OS - Windows + WSL

Look at .env.template for how to create the .env file:
1) Create a .env file in root folder with the filled details (GEMINI_API_KEY, GOOGLE_CLIENT_ID and Secret...)

Create Environment for web app to run:

1) cd path/to/root_directory
2) python -m venv my_venv
3) venv\Scripts\activate
4) pip install -r requirements.txt

How to run:

1) cd path/to/root_directory
2) python -m uvicorn backend.main:app

Go to URL http://127.0.0.1:8000/ (or as indicated in command line)
