#!/bin/bash
# Create virtual environment and install dependencies
python -m venv venv
source venv/bin/activate  # For Linux/Mac
# venv\Scripts\activate  # For Windows

# Install required packages
pip3 install fastapi uvicorn sqlalchemy jinja2 python-multipart python-jose passlib bcrypt shortuuid email-validator pydantic fastapi-sessions python-dotenv

# Create project structure
mkdir -p classroom_app/{templates,static/{css,js,img},models,routers,utils}

# Create necessary files
touch classroom_app/{__init__,main,database,config}.py
touch classroom_app/models/{__init__,users,classes,notifications}.py
touch classroom_app/routers/{__init__,auth,classes,enrollments,notifications}.py
touch classroom_app/utils/{__init__,security,validators}.py
touch classroom_app/static/css/style.css
touch classroom_app/static/js/main.js

# Create template files
touch classroom_app/templates/{base,login,signup,dashboard_student,dashboard_professor,classroom,create_class,join_class,notifications}.html

echo "Project structure created successfully!"