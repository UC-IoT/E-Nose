import firebase_admin
from firebase_admin import credentials, db

cred = credentials.Certificate("project-enose-firebase-adminsdk-fbsvc-ec94e41662.json")
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://project-enose-default-rtdb.firebaseio.com/'
})

ref = db.reference("/test")
ref.set({"hello": "world"})
print("Uploaded test data!")