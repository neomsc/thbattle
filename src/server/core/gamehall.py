import gevent
from gevent import Greenlet
from gevent.event import Event
from gevent.queue import Queue
from utils import PlayerList
from time import time

import logging
import random

log = logging.getLogger('GameHall')

from utils import DataHolder

'''
User state machine:
                       --------------<------------<-----------
                       |                                     |
    -> [Hang] <-> [InRoomWait] <-> [Ready] -> [InGame] -->----
        |                  |         |             |
        --->[[Disconnect]]<-------------------------
'''

games = {} # all games
users = {} # all users
evt_datachange = Event()

class _GameHallStatusUpdator(Greenlet):
    def _run(self):
        last_update = time()
        timeout = None
        evt = evt_datachange
        time_limit = 1
        while True:
            flag = evt.wait()
            delta = time() - last_update
            if delta > time_limit:
                timeout = None
                last_update = time()
                for u in users.values():
                    if u.state == 'hang':
                        send_hallinfo(u)
                evt.clear()
            else:
                gevent.sleep(time_limit - delta)

_GameHallStatusUpdator.spawn()

class UserPlaceHolder(object):

    def __data__(self):
        return dict(
            id=0,
            state='n/a',
        )

    state = 'n/a'
    raw_write = write = lambda *a: False

UserPlaceHolder = UserPlaceHolder()

def new_user(user):
    users[id(user)] = user
    user.state = 'hang'
    evt_datachange.set()

def user_disconnect(user):
    del users[id(user)]
    evt_datachange.set()

def _notify_playerchange(game):
    from client_endpoint import Client
    s = Client.encode(['player_change', game.players])
    for p in game.players:
        p.raw_write(s)

def _next_free_slot(game):
    try:
        return game.players.index(UserPlaceHolder)
    except IndexError as e:
        return None

def create_game(user, gametype, gamename):
    from gamepack import gamemodes
    if not gametype in gamemodes:
        user.write(['gamehall_error', 'gametype_not_exist'])
        return
    g = gamemodes[gametype]()
    g.game_started = False
    g.game_name = gamename
    g.players = PlayerList([UserPlaceHolder] * g.n_persons)
    games[id(g)] = g
    log.info("create game")
    evt_datachange.set()
    return g

def get_ready(user):
    user.state = 'ready'
    g = user.current_game
    _notify_playerchange(g)
    if all(p.state == 'ready' for p in g.players):
        log.info("game starting")
        g.start()

def cancel_ready(user):
    user.state = 'inroomwait'
    _notify_playerchange(user.current_game)

def exit_game(user):
    from game_server import DroppedPlayer
    if user.state != 'hang':
        g = user.current_game
        i = g.players.index(user)
        if g.game_started:
            log.info('player dropped')
            user.write(['fleed', None])
            g.players[i] = DroppedPlayer(g.players[i])
        else:
            log.info('player leave')
            g.players[i] = UserPlaceHolder
            user.write(['game_left', None])

        user.state = 'hang'
        _notify_playerchange(g)
        if all((p is UserPlaceHolder or isinstance(p, DroppedPlayer)) for p in g.players):
            if g.game_started:
                log.info('game aborted')
            else:
                log.info('game canceled')
            del games[id(g)]
            g.kill()
        evt_datachange.set()
    else:
        user.write(['gamehall_error', 'not_in_a_game'])

def join_game(user, gameid):
    if user.state == 'hang' and games.has_key(gameid):
        log.info("join game")
        g = games[gameid]
        slot = _next_free_slot(g)
        if slot is not None:
            user.state = 'inroomwait'
            user.current_game = g
            g.players[slot] = user
            user.write(['game_joined', g])
            _notify_playerchange(g)
            evt_datachange.set()
            return
    user.write(['gamehall_error', 'cant_join_game'])

def quick_start_game(user):
    if user.state == 'hang':
        gl = [g for g in games.values() if _next_free_slot(g) is not None]
        if gl:
            join_game(user, id(random.choice(gl)))
            return
    user.write(['gamehall_error', 'cant_join_game'])

def send_hallinfo(user):
    user.write(['current_games', games.values()])
    user.write(['current_players', users.values()])

def start_game(g):
    log.info("game started")
    g.game_started = True
    for u in g.players:
        u.write(["game_started", None])
        u.state = 'ingame'
        u.__class__ = g.__class__.player_class
        u.gamedata = DataHolder()
    evt_datachange.set()

def end_game(g):
    from game_server import DroppedPlayer
    for p in g.players:
        del p.gamedata

    log.info("end game")
    pl = g.players
    for i, p in enumerate(pl):
        if isinstance(p, DroppedPlayer):
            pl[i] = UserPlaceHolder
    del games[id(g)]
    ng = create_game(None, g.__class__.name, g.game_name)
    ng.players = pl
    for p in pl:
        p.write(['end_game', None])
        p.write(['game_joined', ng])
        p.current_game = ng
        p.state = 'inroomwait'
    _notify_playerchange(ng)
    evt_datachange.set()

def chat(user, msg):
    if user.state == 'hang': # hall chat
        for u in users.values():
            if u.state == 'hang':
                u.write(['chat_msg', [user.nickname, msg]])
    elif user.state in ('inroomwait', 'ready', 'ingame'): # room chat
        for u in user.current_game.players:
            u.write(['chat_msg', [user.nickname, msg]])

def genfunc(_type):
    def _msg(user, msg):
        for u in users.values():
            u.write([_type, [user.nickname, msg]])
    _msg.__name__ = _type
    return _msg

speaker = genfunc('speaker_msg')
system_msg = genfunc('system_msg')
del genfunc