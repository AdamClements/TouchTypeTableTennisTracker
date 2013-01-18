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

def commit_result(result):
  """ Takes a series of parameters representing a match and commits the result,
  changing rankings and news feeds where necessary """
  challenge_success = result['challenge_success']
  defender          = result['defender']
  challenger        = result['challenger']
  defender_score    = result['defender_score']
  challenger_score  = result['challenger_score']

  history_record = MatchHistory(
          defender         = result['defender']        ,
          challenger       = result['challenger']      ,
          defender_score   = result['defender_score']  ,
          challenger_score = result['challenger_score'])

  # Get the two records:
  c_record = Rankings.get_by_key_name(result['challenger'])
  d_record = Rankings.get_by_key_name(result['defender'])
  displace = db.Query(Ranking).filter("rank =" d_record.rank + 1).fetch(1)[0]

  if not c_record or not d_record:
    Exception("No records retrieved for challenger/defender. Crap.")

  if result['challenge_success']:
    c_record.wins += 1
    d_record.loss += 1

    displace.rank, d_record.rank = d_record.rank, displace.rank

    history_record.challenger_rank = c_record.rank
    history_record.defender_rank   = d_record.rank

    c_record.news = "Won %d-%d against %s, moving from rank %s" % \
        ( result['challenger_score'], result['defender_score'],
          get_salutation(result['defender']), d_record.rank )

  else:
    c_record.loss += 1
    d_record.wins += 1

    history_record.challenger_rank = c_record.rank
    history_record.defender_rank   = d_record.rank

    c_record.news = "Unsuccessfully challenged %s, losing %d-%d" % \
        ( get_salutation(result['defender']), result['challenger_score'], result['defender_score'] )

    d_record.news = "Successfully defended against %s, winning %d-%d" % \
        ( get_salutation(result['challenger']), result['defender_score'], result['challenger_score'] )

    db.put([c_record, d_record, history_record])


class MainPage(webapp.RequestHandler):
  def __init__(self):
    self.user_name = get_salutation(users.User().nickname())
    self.email     = users.User().email()

  def get(self):
    """ Basic loading of the normal ladder display, or the twiddle display """
    self.check_user_exists()
    self.display_ladder()

  def post(self):
    """ Handles new inputted results """
    if 'new_result' in self.request.arguments():
      self.confirm_new_result(self.request.get('new_result'))

    elif 'challenger' in self.request.arguments():
      result = {
        'challenge_success' : self.request.get('challenge_success') == "True",
        'defender'          : self.request.get('defender'         ),
        'challenger'        : self.request.get('challenger'       ),
        'defender_score'    : int(self.request.get('defender_score'   )),
        'challenger_score'  : int(self.request.get('challenger_score' )),
        }

      commit_result(result)
      self.display_ladder()
    else:
      raise Exception('Unrecognised POST data')

  def confirm_new_result(self, result_string):
    """ Takes an inputted string and parses it to try and determine the results of
    a match. It assumes that the currently logged in person was one of the participants """

    # Extract numbers (between 0 and 3, hopefully the game scores)
    scores = re.match('.*([0-3]).+([0-3]).*', result_string)
    if not scores:
      raise Exception('Did you give me the score? I\'m looking for two numbers between 0 and 3 and I can\'t see any...')

    score_1 = scores.group(1)
    score_2 = scores.group(2)

    # Extract win/loss sentiment
    winning_words = ['beat', 'won', 'thrashed', 'whitewashed']
    losing_words  = ['beaten by', 'lost', 'thrashed by', 'whitewashed by']

    win_sentiment  = re.search(r'\b%s\b' % r'\b|\b'.join(winning_words), result_string, re.IGNORECASE)
    lose_sentiment = re.search(r'\b%s\b' % r'\b|\b'.join(losing_words) , result_string, re.IGNORECASE)

    # Work out names (possibly shortened)
    possibilities = []
    unigrams = result_string.split(" ")
    opponent = None
    they_won = None

    for name in everybodys_name():
      found = re.search('%s' % name.name().split("@")[0], result_string, re.IGNORECASE)
      if found:
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
          raise Exception('Sorry, I couldn\'t work out who won from that sentence, could you please be a little clearer?')

    if opponent == None:
      raise Exception('Sorry, who did you say you were playing?')

    me = Rankings.get_by_key_name(self.email)
    them = Rankings.get_by_key_name(opponent)

    # Establish challenger/defender order
    challenger = None
    defender = None
    challenger_score = None
    defender_score = None
    challenge_success = None

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
        'challenge_success' : challenge_success
    }

    self.response.out.write(template.render('confirm_result.html', template_values))


  def check_user_exists(self):
    """ Check if the logged in user is on the ladder already, if not sign them up """
    user_record = Rankings.get_by_key_name(self.email)
    if not user_record:
      user_record = Rankings( key_name = self.email,
                              user     = self.user_name,
                              rank     = get_lowest_rank(),
                              news     = "Signed up!")
      user_record.put()

  def display_ladder(self):
    """ Collate all the results and ranking data, feeding them into the ladder display template.
    The ladder template also contains input fields to submit new results """

    rankings  = Rankings.all().order('rank')

    ordered_names = Rankings.all(keys_only=True).order('rank')
    recent_events = MatchHistory.all().order('date_played').fetch(100)

    # This should be do-able in a clever way with lambdas and such
    ranking_timeline_data = []
    for event in recent_events:
      if event.challenger_score > event.defender_score:
        post_match_rankings = ['undefined'] # The first value represents the x axis, seems to be required.
        pre_match_rankings = ['undefined']
        for key in ordered_names:
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

    current_rankings = ['undefined']
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

  def handle_exception(self, exception, debug=True):
    template_values = {
        'message' : exception,
    }

    self.response.out.write(template.render('error_template.html', template_values))

application = webapp.WSGIApplication([
    ('/',        MainPage       ),
  ], debug=True)

def main():
  run_wsgi_app(application)

if __name__ == "__main__":
  main()
