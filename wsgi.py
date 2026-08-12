import sys
import os

path = '/home/<your-username>/patient_form'
if path not in sys.path:
    sys.path.insert(0, path)

os.environ['SMTP_HOST'] = 'smtp.gmail.com'
os.environ['SMTP_PORT'] = '587'
os.environ['SMTP_USER'] = 'sialihako@gmail.com'
os.environ['SMTP_PASS'] = 'wmavktnoybyfzsxu'
os.environ['FROM_EMAIL'] = 'sialihako@gmail.com'
os.environ['FROM_NAME'] = 'BCI'
os.environ['BCC_EMAIL'] = ''

from app import app as application
