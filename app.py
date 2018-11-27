import sys, os
from flask import Flask, g, session, redirect, request, jsonify, render_template, send_from_directory, Markup
from requests_oauthlib import OAuth2Session
from uuid import uuid4
import json, tinydb, re
import requests
import time
from markdown import markdown

if "--local" in sys.argv:
    config = json.loads(open('local-config.json', 'r').read())
else:
    config = json.loads(open('/home/akira/support.twitchbot.io/config.json', 'r').read())

OAUTH2_CLIENT_ID = config['client_id']
OAUTH2_CLIENT_SECRET = config['client_secret']
OAUTH2_REDIRECT_URI = config['redirect_uri']

API_BASE_URL = os.environ.get('API_BASE_URL', 'https://discordapp.com/api')
AUTHORIZATION_BASE_URL = API_BASE_URL + '/oauth2/authorize'
TOKEN_URL = API_BASE_URL + '/oauth2/token'

app = Flask(__name__)
app.debug = config['debug']
app.config['SECRET_KEY'] = OAUTH2_CLIENT_SECRET

if os.name == 'darwin':
    db = tinydb.TinyDB("/home/akira/support.twitchbot.io/database.db")
else:
    db = tinydb.TinyDB("database.db")
articles = db.table('articles')
users = db.table('users')

if 'http://' in OAUTH2_REDIRECT_URI:
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = 'true'


def token_updater(token):
    session['oauth2_token'] = token


def make_session(token=None, state=None, scope=None):
    return OAuth2Session(
        client_id=OAUTH2_CLIENT_ID,
        token=token,
        state=state,
        scope=scope,
        redirect_uri=OAUTH2_REDIRECT_URI,
        auto_refresh_kwargs={
            'client_id': OAUTH2_CLIENT_ID,
            'client_secret': OAUTH2_CLIENT_SECRET,
        },
        auto_refresh_url=TOKEN_URL,
        token_updater=token_updater)


def twbot_request(method, url, data=None):
    headers = {"Authorization": "Bot {}".format(config['bot_token'])}
    if method == 'POST':
        headers['Content-Type'] = 'application/json'
    r = requests.request(method, url, headers=headers, data=data)
    return r


@app.route('/')
def index():
    discord = make_session(token=session.get('oauth2_token'))
    user = discord.get(API_BASE_URL + '/users/@me').json()
    admin = False
    if discord.authorized:
        admin = users.get(tinydb.Query().id == user['id'])['admin']
    return render_template('index.html', discord=discord, user=user, admin=admin)


@app.route('/assets/<fname>')
def get_asset(fname):
    return send_from_directory('assets', fname)


@app.route('/oauth')
def oauth():
    discord = make_session(scope=["identify"])
    authorization_url, state = discord.authorization_url(AUTHORIZATION_BASE_URL)
    session['oauth2_state'] = state
    session['next'] = request.args.get('next', '')
    return redirect(authorization_url)


@app.route('/oauth/authorize')
def authorize():
    if request.values.get('error'):
        return request.values['error']
    discord = make_session(state=session.get('oauth2_state'))
    token = discord.fetch_token(
        TOKEN_URL,
        client_secret=OAUTH2_CLIENT_SECRET,
        authorization_response=request.url)
    session['oauth2_token'] = token
    # get user info
    discord = make_session(token=session.get('oauth2_token'))
    user = discord.get(API_BASE_URL + '/users/@me').json()
    guild_member = twbot_request('GET', API_BASE_URL + "/guilds/294215057129340938/members/{}".format(user['id'])).json()
    admin = True
    if not "roles" in guild_member.keys():
        admin = False
    elif not "424762262775922692" in guild_member['roles']:
        admin = False
    users.upsert({**user, "admin": admin}, tinydb.Query().id == user['id'])
    return redirect('/' + session.get('next', ''))


@app.route('/oauth/deauthorize')
def deauthorize():
    del session['oauth2_token']
    return redirect('/')


@app.route('/me')
def me():
    discord = make_session(token=session.get('oauth2_token'))
    user = discord.get(API_BASE_URL + '/users/@me').json()
    if not discord.authorized:
        return redirect('/oauth?next=me')
    admin = users.get(tinydb.Query().id == user['id'])['admin']
    my_articles = articles.search(tinydb.Query().creator_id == user['id'])
    return render_template('category.html', discord=discord, user=user, articles=my_articles, category="My Articles", admin=admin)


@app.route('/articles/new', methods=["GET", "POST"])
def new_article():
    discord = make_session(token=session.get('oauth2_token'))
    user = discord.get(API_BASE_URL + '/users/@me').json()
    if not discord.authorized:
        return redirect('/oauth?next=article/new')
    admin = users.get(tinydb.Query().id == user['id'])['admin']
    if not admin:
        return abort(403)
    if request.method == 'GET':
        return render_template('new_article.html', user=user)
    elif request.method == 'POST':
        data = {
            "article_id": str(uuid4()),
            "creator_id": user['id'],
            "created_at": time.time(),
            "title": request.values['title'],
            "category": request.values['category'],
            "content": request.values['content']
        }
        articles.insert(data)
        return redirect('/articles/' + data['article_id'])


@app.route('/articles/<id>')
def get_article(id):
    discord = make_session(token=session.get('oauth2_token'))
    user = discord.get(API_BASE_URL + '/users/@me').json()
    admin = False
    if discord.authorized:
        admin = users.get(tinydb.Query().id == user['id'])['admin']
    article = articles.get(tinydb.Query().article_id == id)
    if article is None:
        return abort(404)
    article['content'] = Markup(markdown(article['content']))
    article['author'] = users.get(tinydb.Query().id == article['creator_id'])
    article['created_at'] = time.strftime("%b %d, %Y", time.gmtime(article['created_at']))
    return render_template('article.html', article=article, discord=discord, user=user, admin=admin)


@app.route('/articles/<id>/edit', methods=['GET', 'POST'])
def edit_article(id):
    discord = make_session(token=session.get('oauth2_token'))
    user = discord.get(API_BASE_URL + '/users/@me').json()
    if not discord.authorized:
        return redirect('/oauth?next=articles/{}/edit'.format(id))
    admin = users.get(tinydb.Query().id == user['id'])['admin']
    if not admin:
        return abort(403)
    article = articles.get(tinydb.Query().article_id == id)
    if article is None:
        return abort(404)
    if request.method == 'GET':
        return render_template('edit_article.html', user=user, article=article)
    elif request.method == 'POST':
        data = {
            "title": request.values['title'],
            "category": request.values['category'],
            "content": request.values['content']
        }
        articles.update(data, tinydb.Query().article_id == id)
        return redirect('/articles/' + id)


@app.route('/articles/<id>/delete', methods=['POST'])
def del_article(id):
    discord = make_session(token=session.get('oauth2_token'))
    user = discord.get(API_BASE_URL + '/users/@me').json()
    if not discord.authorized:
        return redirect('/oauth?next=articles/{}/edit'.format(id))
    admin = users.get(tinydb.Query().id == user['id'])['admin']
    if not admin:
        return abort(403)
    article = articles.get(tinydb.Query().article_id == id)
    if article is None:
        return abort(404)
    articles.remove(doc_ids=[article.doc_id])
    return redirect('/me')


def same_cat(c1, c2):
    return c1.lower() == c2.lower()

@app.route('/category/<c>')
def get_category(c):
    discord = make_session(token=session.get('oauth2_token'))
    user = discord.get(API_BASE_URL + '/users/@me').json()
    admin = False
    if discord.authorized:
        admin = users.get(tinydb.Query().id == user['id'])['admin']
    data = articles.search(tinydb.Query().category.test(same_cat, c))
    return render_template('category.html', discord=discord, user=user, articles=data, category=c.capitalize(), admin=admin)


def get_res(obj, term):
    return term.lower() in obj.lower()

@app.route('/search')
def search():
    discord = make_session(token=session.get('oauth2_token'))
    user = discord.get(API_BASE_URL + '/users/@me').json()
    admin = False
    if discord.authorized:
        admin = users.get(tinydb.Query().id == user['id'])['admin']
    term = request.args.get('q')
    if term is None:
        return redirect('/')
    data = articles.search(tinydb.Query().title.test(get_res, term) | tinydb.Query().category.test(get_res, term))
    return render_template('search.html', discord=discord, user=user, articles=data, term=term, admin=admin)


if __name__ == '__main__':
    app.run('0.0.0.0', port=80)
