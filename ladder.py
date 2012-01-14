import os
from google.appengine.ext.webapp import template
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.api import users
from google.appengine.ext import db

class History(db.Model):
  defender         = db.UserProperty     (required=True)
  challenger       = db.UserProperty     (required=True)
  defender_score   = db.IntegerProperty  (required=True)
  challenger_score = db.IntegerProperty  (required=True)
  date_played      = db.DateTimeProperty (auto_now_add=True)

class Rankings(db.Model):
  user = db.UserProperty    (required=True)
  rank = db.IntegerProperty (required=True)
  news = db.StringProperty  (required=False, default="")
  wins = db.IntegerProperty (required=False, default=0 )
  loss = db.IntegerProperty (required=False, default=0 )

def get_salutation(jid):
  return jid.split("@")[0].replace(".", " ").title() 

class MainPage(webapp.RequestHandler):
  def get(self):
    #usertotals = PerUserTotals.all().order('-cupsDrunk').fetch(999)
    #pastweek  = PerUserStats.all().fetch(50)
    
    template_values = {
        'user': get_salutation(users.User().nickname()),
        'email' : users.User().email(),
    }
    
    path = os.path.join(os.path.dirname(__file__), 'ladder_template.html')
    self.response.out.write(template.render(path, template_values))
      
application = webapp.WSGIApplication([('/', MainPage)], debug=True)

def main():
  run_wsgi_app(application)

if __name__ == "__main__":
  main()
