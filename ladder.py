import os
import logging
import re

from time import gmtime, strftime

from google.appengine.ext.webapp import template
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.api import users
from google.appengine.ext import db

class MatchHistory(db.Model):
  """ Stores all the matches that take place along with dates
  and scores """
  defender         = db.StringProperty   (required=True)
  challenger       = db.StringProperty   (required=True)
  defender_score   = db.IntegerProperty  (required=True)
  challenger_score = db.IntegerProperty  (required=True)
  defender_rank    = db.IntegerProperty  (required=False)   # Might be undefined if the rank is unaffected
  challenger_rank  = db.IntegerProperty  (required=False)   # Note: This is the rank *after* the match
  ladder_game      = db.BooleanProperty  (required=False, default=False)
  date_played      = db.DateTimeProperty (auto_now_add=True)

class Rankings(db.Model):
  """ The overall ranking table, user is the unique key, 
  ranking changes. News may be an arbitrary string, usually
  the last win/loss. The key_name for this table is the
  user's email address """
  user = db.StringProperty  (required=True)
  rank = db.IntegerProperty (required=True)
  news = db.StringProperty  (required=False, default="")
  wins = db.IntegerProperty (required=False, default=0 )
  loss = db.IntegerProperty (required=False, default=0 )

def get_salutation(email):
  """ Take a guess at how to address someone based on the first
  segment of their email address """
  return email.split("@")[0].replace(".", " ").title() 

def everybodys_name():
  """ Get a list of everybody's names for reverse name matching """
  return Rankings.all(keys_only=True)

def get_lowest_rank():
  """ Query the database for the lowest ranked person, in order
  to add a new person to the bottom rung of the ladder """
  lowest_ranking = Rankings.all().order('-rank').get()
  if lowest_ranking == None:
    return 1
  else:
    return lowest_ranking.rank + 1

class MainPage(webapp.RequestHandler):
  def __init__(self):
    self.user_name = get_salutation(users.User().nickname())
    self.email     = users.User().email()

  def get(self):
    if 'new_result' in self.request.arguments():
      self.confirm_new_result(self.request.get('new_result'))

    elif 'challenger' in self.request.arguments():
      self.commit_result()
      self.display_ladder()          

    else:
      self.check_user_exists()
      self.display_ladder()

  def confirm_new_result(self, result_string):
    # Extract numbers (between 0 and 3, game scores)
    scores = re.match('.*([0-3]).+([0-3]).*', result_string)
    if not scores:
      raise Exception('Couldn\'t match any scores')

    score_1 = scores.group(1)
    score_2 = scores.group(2)

    # Extract win/loss sentiment
    win_sentiment = re.search('beat|won|thrashed', result_string, re.IGNORECASE)
    lose_sentiment = re.search('lost', result_string, re.IGNORECASE)

    # Work out names (possibly shortened)
    possibilities = []
    unigrams = result_string.split(" ")
    opponent = None
    they_won = None

    for name in everybodys_name():
      logging.info('Checking against %s' % name.name().split('@')[0])
      found = re.search('%s' % name.name().split("@")[0], result_string, re.IGNORECASE)
      if found:
        logging.info('Found!')
        opponent = name.name()
        if win_sentiment and win_sentiment.start() < found.start():
          they_won = True
        elif win_sentiment and win_sentiment.start() > found.start():
          they_won = False
        elif lose_sentiment and lose_sentiment.start() < found.start():
          they_won = False
        elif lose_sentiment and lose_sentiment.start() > found.start():
          they_won = True
        else:
          raise Exception('Couldn\'t work out who won, didn\'t detect a win/lose sentiment')

    if opponent == None:
      raise Exception('Found no opponent!!')
    
    me = Rankings.get_by_key_name(self.email)
    them = Rankings.get_by_key_name(opponent)
    
    # Establish challenger/defender order
    challenger = None
    defender = None
    challenger_score = None
    defender_score = None
    challenge_success = None
    ladder_game = abs(me.rank - them.rank) <=3

    if me.rank < them.rank:
      challenger = them.key().name()
      defender = me.key().name()
      if they_won:
        challenge_success = False
        challenger_score = min(score_1, score_2)
        defender_score = max(score_1, score_2)
      else:
        challenge_success = True
        challenger_score = max(score_1, score_2)
        defender_score = min(score_1, score_2)
    else:
      challenger = me.key().name()
      defender = them.key().name()
      if they_won:
        challenge_success = True
        challenger_score = max(score_1, score_2)
        defender_score = min(score_1, score_2)
      else:
        challenge_success = False
        challenger_score = min(score_1, score_2)
        defender_score = max(score_1, score_2)

    template_values = {
        'challenger'        : challenger,
        'defender'          : defender,
        'challenger_name'   : get_salutation(challenger),
        'defender_name'     : get_salutation(defender),
        'challenger_score'  : challenger_score,
        'defender_score'    : defender_score,
        'challenge_success' : challenge_success,
        'ladder_game'       : ladder_game,
    }
    
    self.response.out.write(template.render('confirm_result.html', template_values))
  
  def commit_result(self):
    challenge_success = self.request.get('challenge_success') == "True"
    ladder_game       = self.request.get('ladder_game'      ) == "True"
    defender          = self.request.get('defender'         )
    challenger        = self.request.get('challenger'       )
    defender_score    = int(self.request.get('defender_score'   ))
    challenger_score  = int(self.request.get('challenger_score' ))

    history_record = MatchHistory(
            defender         = defender        ,
            challenger       = challenger      ,
            defender_score   = defender_score  ,
            challenger_score = challenger_score,
            ladder_game      = ladder_game     )

    # Get the two records:
    c_record = Rankings.get_by_key_name(challenger)
    d_record = Rankings.get_by_key_name(defender)

    if not c_record or not d_record:
      Exception("No records retrieved for challenger/defender. Crap.")
      
    if challenge_success:
      c_record.wins += 1
      d_record.loss += 1
      
      if ladder_game:
        c_record.rank, d_record.rank = d_record.rank, c_record.rank

        history_record.challenger_rank = c_record.rank
        history_record.defender_rank   = d_record.rank

        c_record.news = "Won %d-%d against %s, moving to rank %s" % \
                        ( challenger_score, defender_score,
                          get_salutation(defender), c_record.rank )

        d_record.news = "Lost %d-%d to %s, dropping to rank %s" % \
                        ( defender_score, challenger_score,
                          get_salutation(challenger), d_record.rank )
      else:
        c_record.news = "Won a friendly %d-%d against %s" % \
                        ( challenger_score, defender_score, 
                          get_salutation(defender) )
        # Isn't really news losing a friendly... don't bother
    else:
      c_record.loss += 1
      d_record.wins += 1
      
      if ladder_game:
        history_record.challenger_rank = c_record.rank
        history_record.defender_rank   = d_record.rank

        c_record.news = "Unsuccessfully challenged %s, losing %d-%d" % \
                        ( get_salutation(defender), challenger_score, defender_score )

        d_record.news = "Successfully defended against %s, winning %d-%d" % \
                        ( get_salutation(challenger), defender_score, challenger_score )
      else:
        d_record.news = "Won a friendly %d-%d against %s" % \
                        ( defender_score, challenger_score, get_salutation(challenger) )

    db.put([c_record, d_record, history_record])

  def check_user_exists(self):
    # First see if this user is on the ladder already, if not sign them up
    user_record = Rankings.get_by_key_name(self.email)
    if not user_record:
      user_record = Rankings( key_name = self.email, 
                              user     = self.user_name,
                              rank     = get_lowest_rank(),
                              news     = "Signed up!")
      user_record.put()
    
  def display_ladder(self):
    rankings  = Rankings.all().order('rank')

    ordered_names = Rankings.all(keys_only=True).order('rank')
    recent_events = MatchHistory.all().order('date_played').fetch(100)
    i = 0
    # This should be do-able in a clever way with lambdas and such
    ranking_timeline_data = []
    for event in recent_events:
      if event.ladder_game and event.challenger_score > event.defender_score:
        post_match_rankings = []
        pre_match_rankings = []
        for key in ordered_names:
          logging.info("Ladder game: %s, Chall: %s, Def %s" %(event.ladder_game, event.challenger_rank, event.defender_rank))
          name = key.name()
          if name == event.challenger:
            post_match_rankings.append("%s" % event.challenger_rank)
            pre_match_rankings.append("%s" % event.defender_rank)
          elif name== event.defender:
            post_match_rankings.append("%s" % event.defender_rank)
            pre_match_rankings.append("%s" % event.challenger_rank)
          else:
            post_match_rankings.append('undefined')
            pre_match_rankings.append('undefined')
        ranking_timeline_data.append("[%s]," % ( ",".join(pre_match_rankings)))
        ranking_timeline_data.append("[%s]," % ( ",".join(post_match_rankings)))
    
    current_rankings = []
    for key in rankings:
      current_rankings.append("%s" % key.rank)
    ranking_timeline_data.append("[%s]," % (",".join(current_rankings)))
    ranking_timeline_data.append("[%s]," % (",".join(current_rankings)))

    ordered_people = []
    for key in ordered_names:
      ordered_people.append(get_salutation(key.name()))

    template_values = {
        'user': self.user_name,
        'email' : self.email,
        'rankings' : rankings,
        'ordered_people' : ordered_people,
        'ranking_timeline_data' : ranking_timeline_data,
    }
    
    self.response.out.write(template.render('ladder_template.html', template_values))

      
application = webapp.WSGIApplication([('/', MainPage)], debug=True)

def main():
  run_wsgi_app(application)

if __name__ == "__main__":
  main()
