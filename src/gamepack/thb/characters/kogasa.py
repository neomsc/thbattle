# -*- coding: utf-8 -*-
from .baseclasses import *
from ..actions import *
from ..skill import *
from ..cards import *

class Jolly(Skill):
    associated_action = None
    target = t_None

class Surprise(GenericAction):
    def apply_action(self):
        src = self.source
        tgt = self.target
        suit = tgt.user_input('choose_option', self)
        card = random_choose_card([src.cards, src.showncards])
        src.tags['surprise_tag'] = src.tags['turn_count']
        if not card: return False
        g = Game.getgame()
        g.players.exclude(src).reveal(card)
        if card.suit != suit:
            dmg = Damage(src, tgt)
            dmg.associated_action = self
            g.process_action(dmg)
        if not tgt.dead:
            migrate_cards([card], tgt.cards)

        return True

    def is_valid(self):
        src = self.source
        if src.tags.get('turn_count', 0) <= src.tags.get('surprise_tag', 0):
            return False
        if not (src.cards or src.showncards):
            return False
        return True

class SurpriseSkill(Skill):
    associated_action = Surprise
    target = t_OtherOne
    no_drop = True
    no_reveal = True
    def check(self):
        return True

class JollyHandler(EventHandler):
    def handle(self, evt_type, act):
        if evt_type == 'action_before' and isinstance(act, DrawCardStage):
            tgt = act.target
            if tgt.has_skill(Jolly):
                act.amount += 1
        return act

@register_character
class Kogasa(Character):
    skills = [SurpriseSkill, Jolly]
    eventhandlers_required = [JollyHandler]
    maxlife = 3