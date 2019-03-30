/* Setting things up. */
var path = require('path'),
    express = require('express'),
    app = express(),   
    http = require('http'),
    Twit = require('twit'),
    //json = require('json'),
    config = {
    /* Be sure to update the .env file with your API keys. See how to get them: https://botwiki.org/tutorials/how-to-create-a-twitter-app */      
      twitter: {
        consumer_key: process.env.CONSUMER_KEY,
        consumer_secret: process.env.CONSUMER_SECRET,
        access_token: process.env.ACCESS_TOKEN,
        access_token_secret: process.env.ACCESS_TOKEN_SECRET
      }
    },
    T = new Twit(config.twitter),
    mongoose = require('mongoose');
    mongoose.connect('mongodb://dbuser2:user123@ds127736.mlab.com:27736/qurandb', {useNewUrlParser: true});
    var Info = mongoose.model('info', { date: Date, current_verse: Number, current_chapter: Number, current_verse_ind: Number });
const url = "staging.quran.com";
const NUM_OF_CHAPTERS = 144;
function get_chapter_info(chapter_number, callback){
  var options = {
    host: url,
    port: 3000,
    path: '/api/v3/chapters/' + chapter_number,
    method: 'GET'
  };
  http.request(options, function(res) {
    console.log('STATUS: ' + res.statusCode);
    console.log('HEADERS: ' + JSON.stringify(res.headers));
    res.setEncoding('utf8');
    var bodyChunks = "";
    res.on('data', function(data){
      bodyChunks+=data;
    });
    res.on('end', function(){
      console.log(bodyChunks);
      var body = bodyChunks;
      console.log('BODY: ' + body);
      callback(null,JSON.parse(body).chapter);  
    });
  }).end();
}

function get_verse(chapter_number, verse_number, callback){
  var options = {
    host: url,
    port: 3000,
    path: '/api/v3/chapters/' + chapter_number + '/verses/?offset=' + verse_number +'&limit=1&text_type=words',
    method: 'GET'
  };
  http.request(options, function(res) {
    console.log('STATUS: ' + res.statusCode);
    console.log('HEADERS: ' + JSON.stringify(res.headers));
    res.setEncoding('utf8');
    var bodyChunks = "";
    res.on('data', function(data){
      bodyChunks += data;
    });
    res.on('end', function(){
      var body = bodyChunks;
      console.log('BODY: ' + body);
      if(res.statusCode == 200){
        // console.log("here");
        callback(null,JSON.parse(body).verses[0]);
      }
       
    });
  }).end();
}

function post_tweet(tweet, callback){
  /* The example below tweets out "Hello world!". */
  T.post('statuses/update', { status: tweet }, function(err, data, response) {
    callback(err,data);
  });
}

app.use(express.static('public'));
/* You can use cron-job.org, uptimerobot.com, or a similar site to hit your /BOT_ENDPOINT to wake up your app and make your Twitter bot tweet. */

app.all(`/${process.env.BOT_ENDPOINT}`, function(req, res){
  var current = null;
  Info.find(function(err, found){
    if(err || !found.length){
      current = new Info({date: Date(), current_verse: 1, current_chapter: 1, current_verse_ind: 0});
    }else{
      found[0].current_verse++;
      found = new Info(found[0]);
      current = found;
    }
    if(current != null){
      //get current chapter
      get_chapter_info(current.current_chapter, function(err, res1){
        //check if current verse is the last in the current chapter
        var current_chapter = res1;
        //console.log("res1: " + res1);
        if(current_chapter){
          if(current_chapter.verses_count < current.current_verse){
            //if not the last chapter move on to the next chapter
            if(current.current_chapter < NUM_OF_CHAPTERS){
              current.current_chapter = current.current_chapter+1;
              current.current_verse = 1;
            }else{
              //else back to the beginning
              current.current_chapter = 1;
              current.current_verse = 1;
            }
          }
          get_chapter_info(current.current_chapter, function(err, res2){
            current_chapter = res2;
            //console.log("res2: " + res2);
            get_verse(current.current_chapter, current.current_verse,
            function(err, res3){
              var current_verse = res3;
              if(current_verse){
                var arabic_verse = '"' + current_verse.text_madani + '"-{' + 
                    current_chapter.name_arabic + ':' + current.current_verse + '}';
                console.log(arabic_verse);
                var english_verse = "";
                for(var i = 0; i <  current_verse.words.length; i++){
                  //console.log(current_verse.words[i]);
                  if(current_verse.words[i].translation){
                    english_verse += current_verse.words[i].translation.text;
                  }

                }
                english_verse = '"' + english_verse + '"-{' + 
                    current_chapter.translated_name.name + ':' + current.current_verse + '}'; 
                console.log(english_verse);
                //TODO: check if it fits in a tweet
                //post verse in arabic + chapter_name + verse_number
                var ret_obj_ar = post_tweet(arabic_verse, function(err){
                  //attach verse in english + chapter_name + verse_number
                  if(!err){
                    var ret_obj_en = post_tweet(english_verse,function(err){
                      if(!err){
                        //update current verse in database
                        current.save(function (err, saveRes) {
                          if(err){
                            console.log("error saving state: " + err);
                          }else{
                            console.log("state updated");
                          }
                        });
                      }
                  
                    });
                  }
                
                });
                
              }
            });

          });
          
          
        }
      });
      
      
      
    }
    res.send( "Hi there bot is waving");
  });
  
  
});

var listener = app.listen(process.env.PORT, function(){
  console.log('Your bot is running on port ' + listener.address().port);
});

