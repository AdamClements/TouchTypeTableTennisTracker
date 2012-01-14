import os
import logging

from google.appengine.ext.webapp import template
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.api import users
from google.appengine.ext import db

class History(db.Model):
  """ Stores all the matches that take place along with dates
  and scores """
  defender         = db.StringProperty   (required=True)
  challenger       = db.StringProperty   (required=True)
  defender_score   = db.IntegerProperty  (required=True)
  challenger_score = db.IntegerProperty  (required=True)
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

def get_lowest_rank():
  """ Query the database for the lowest ranked person, in order
  to add a new person to the bottom rung of the ladder """
  return Rankings.all().order('-rank').get().rank + 1

class MainPage(webapp.RequestHandler):
  def __init__(self):
    self.user_name = get_salutation(users.User().nickname())
    self.email     = users.User().email()

  def get(self):
    if 'new_result' in self.request.arguments():
      self.confirm_new_result(self.request.get('new_result'))

    elif 'challenger' in self.request.arguments():
      self.commit_result(self.request.arguments())
      self.display_ladder()          

    else:
      self.check_user_exists()
      self.display_ladder()

  def confirm_new_result(self, result_string):
    challenger = "myface@example.com"
    defender = "test@example.com"
    challenger_score = 3
    defender_score = 2
    challenge_success = True
    ladder_game = True

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
  
  def commit_result(self, results):
    challenge_success = self.request.get('challenge_success') == "True"
    ladder_game       = self.request.get('ladder_game'      ) == "True"
    defender          = self.request.get('defender'         )
    challenger        = self.request.get('challenger'       )
    defender_score    = int(self.request.get('defender_score'   ))
    challenger_score  = int(self.request.get('challenger_score' ))

    logging.info("Got " + str(defender_score))

    history_record = History(
            defender         = defender        ,
            challenger       = challenger      ,
            defender_score   = defender_score  ,
            challenger_score = challenger_score,
            ladder_game      = ladder_game     )

    history_record.put()

    # Get the two records:
    c_record = Rankings.get_by_key_name(challenger)
    d_record = Rankings.get_by_key_name(defender)

    if not c_record or not d_record:
      Error("No records retrieved for challenger/defender. Crap.")
      
    if challenge_success:
      c_record.wins += 1
      d_record.loss += 1
      
      if ladder_game:
        c_record.rank, d_record.rank = d_record.rank, c_record.rank

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
        c_record.news = "Unsuccessfully challenged %s, losing %d-%d" % \
                        ( get_salutation(defender), challenger_score, defender_score )

        d_record.news = "Successfully defended against %s, winning %d-%d" % \
                        ( get_salutation(challenger), defender_score, challenger_score )
      else:
        d_record.news = "Won a friendly %d-%d against %s" % \
                        ( defender_score, challenger_score, get_salutation(challenger) )

    c_record.put()
    d_record.put()

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

    template_values = {
        'user': self.user_name,
        'email' : self.email,
        'rankings' : rankings,
    }
    
    self.response.out.write(template.render('ladder_template.html', template_values))

      
application = webapp.WSGIApplication([('/', MainPage)], debug=True)

def main():
  run_wsgi_app(application)

if __name__ == "__main__":
  main()
