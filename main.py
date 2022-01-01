from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import pyrebase
from pymongo import MongoClient
import asyncio
import os
import json
from dotenv import load_dotenv
load_dotenv()

# Google APIs
SCOPES = ['https://www.googleapis.com/auth/classroom.courses', 'https://www.googleapis.com/auth/classroom.rosters', 'https://www.googleapis.com/auth/classroom.guardianlinks.students',
          'https://www.googleapis.com/auth/classroom.profile.photos', 'https://www.googleapis.com/auth/classroom.profile.emails', 'https://www.googleapis.com/auth/classroom.topics']

# MongoDB
MONGO_STRING = os.environ['mongo_string']
CLIENT = MongoClient(MONGO_STRING)
DATABASE = CLIENT[os.environ['database']]
ALUNOS = [x for x in DATABASE['alunos'].find()]
PROFESSORES = [x for x in DATABASE['professores'].find()]
SCH_NAME = os.environ['sch']

# Firebase
with open('firebase.json', 'r', encoding='UTF-8') as file:
    config = json.loads(file.read())
firebase = pyrebase.initialize_app(config)
db = firebase.database()

# Inicio da Aplicação


def main():
    print("Superintendente v2.0")

    # Firebase - Leitura Salas
    classData = db.child("salas").get().val()
    # Firebase - Leitura Tópicos
    topicsData = db.child("topics").get().val()
    # Serviço do Google Classroom
    classroomService = googleAuth()

    # Verificação e criação de salas
    verifyAndCreateRooms(classroomService, classData)

    # Inicia o gerenciamento de turmas
    roomHubMaintenance(classroomService, classData)

# Autenticação Google


def googleAuth():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    service = build('classroom', 'v1', credentials=creds)
    return service

# GET em todas as salas do classroom


def getRooms(service):
    return service.courses().list().execute()['courses']
# Filtra salas não arquivadas


def nonAchievedRooms(rooms):
    return list(filter(lambda x: x['courseState'] != 'ARCHIVED', rooms))

# Cria sala no Classroom


def createRoom(service, data, key):
    if type(data['turno']) == list:
        turno = ''
    else:
        turno = ' - ' + data['turno']
    novaSala = {
        'name': data['name'],
        'description': SCH_NAME + ' - ' + data['turma'] + turno,
        'room': key,
        'section': SCH_NAME,
        'ownerId': 'me'
    }
    sala = service.courses().create(body=novaSala).execute()
    try:
        return sala != None
    except:
        pass

# Verificação e criação de salas


def verifyAndCreateRooms(service, firebaseRooms):
    actualRooms = list(
        map(lambda x: x['room'], nonAchievedRooms(getRooms(service))))
    roomsDatabase = [x for x in firebaseRooms]
    roomsToCreate = list(filter(lambda x: x not in actualRooms, roomsDatabase))
    for x in roomsToCreate:
        createRoom(service, firebaseRooms[x], x)

    # Aceitar turmas pendentes
    convites = service.invitations().list(userId="me", pageSize=500).execute()
    print(convites)

# Hub de Sala no Classroom


def roomHubMaintenance(service, firebaseRooms):
    actualRooms = list(map(lambda x: x, nonAchievedRooms(getRooms(service))))
    roomsDatabase = [x for x in firebaseRooms]
    for x in actualRooms:
        roomMaintenance(service, x, firebaseRooms[x['room']]) if (
            x['room'] in roomsDatabase) else print('')


# Manutenção de sala
def roomMaintenance(service, room, firebaseData):
    # Professores
    professores(service, room, firebaseData['teachers'])
    # Alunos
    alunos(service, room, firebaseData)
    # Tópicos
    topics(service, room, firebaseData)

# Professores


def professores(service, room, teachers):
    profsGet = list(map(lambda x: (x['profile']['emailAddress'], x['profile']['id']), service.courses(
    ).teachers().list(courseId=room['id']).execute()['teachers']))
    teachersInvited = checkTeachersInvites(service, room)
    teachersToInvite = list(
        filter(lambda x: x not in profsGet and x not in teachersInvited, teachers))
    for teacher in teachersToInvite:
        newTeacher = {"courseId": room['id'],
                      "userId": teacher, "role": "TEACHER"}
        service.invitations().create(body=newTeacher).execute()
    teachersToRemove = list(filter(
        lambda x: x not in teachers and x[0] != os.environ['userLogged'], profsGet))
    for teacher in teachersToRemove:
        service.courses().teachers().delete(
            courseId=room['id'], userId=teacher).execute()

# Alunos


def alunos(service, room, firebaseParams):
    stds = list(filter(lambda x: x['enabled'] == True and x['turma']
                in firebaseParams['turma'] and x['turno'] == firebaseParams['turno'], ALUNOS))
    stdsOnRoom = service.courses().students().list(
        courseId=room['id']).execute()
    stdsGet = list(map(lambda x: x['profile']['emailAddress'], stdsOnRoom['students'] if (
        'students' in stdsOnRoom) else []))
    studentsInvited = checkStudentsInvites(service, room)
    stdsToInvite = list(
        filter(lambda x: x not in stdsGet and x not in studentsInvited, stds))
    for stdnt in stdsToInvite:
        newStd = {"courseId": room['id'],
                  "userId": stdnt['email'], "role": "STUDENT"}
        service.invitations().create(body=newStd).execute()
    stdsToRemove = list(filter(lambda x: x not in stds, stdsGet))
    for stdnt in stdsToRemove:
        service.courses().students().delete(
            courseId=room['id'], userId=stdnt).execute()

# Topicos


def topics(service, room, firebaseParams):
    topicsList = db.child("topics").get().val()[firebaseParams['topics']]
    topicsOnRoom = service.courses().topics().list(
        courseId=room['id']).execute()
    topicsGet = list(map(lambda x: x['name'], topicsOnRoom['topic'] if (
        'topic' in topicsOnRoom) else []))
    topicsToCreate = list(filter(lambda x: x not in topicsGet, topicsList))
    for topic in topicsToCreate[::-1]:
        topicNew = {"courseId": room['id'], "name": topic}
        service.courses().topics().create(
            courseId=room['id'], body=topicNew).execute()
# CheckTeachersInvites


def checkTeachersInvites(service, room):
    invites = service.invitations().list(courseId=room['id']).execute()
    if 'invitations' in invites:
        return list(map(lambda x: service.userProfiles().get(userId=x['userId']).execute()['emailAddress'], invites['invitations']))
    else:
        return []

# CheckStudentsInvites


def checkStudentsInvites(service, room):
    invites = service.invitations().list(courseId=room['id']).execute()
    if 'invitations' in invites:
        return list(map(lambda x: service.userProfiles().get(userId=x['userId']).execute()['emailAddress'], invites['invitations']))
    else:
        return []


main()
