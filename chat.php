<?php
session_start();
if (empty($_SESSION['user'])) {
    header('Location: index.php');
    exit;
}
$user = $_SESSION['user'];
?>
<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Мессенджер</title>
<style>
body { font-family:'Segoe UI',Arial,sans-serif; margin:0; background:#e9eef3; }
.wrap { display:flex; height:100vh; }
.chat { flex:1; display:flex; flex-direction:column; min-width:0; }
.side { width:200px; background:#f4f6f8; border-right:1px solid #d5dbe1; padding:12px; overflow:auto; }
.side h3 { margin:0 0 10px; font-size:14px; color:#444; word-break:break-word; }
#users { list-style:none; margin:0; padding:0; }
#users li { padding:6px 8px; font-size:14px; word-break:break-word; }
#users li.me { font-weight:bold; }
.msgs { flex:1; overflow-y:auto; padding:16px; }
.msg { background:#fff; border-radius:8px; padding:8px 12px; margin-bottom:10px; max-width:70%; box-shadow:0 1px 2px rgba(0,0,0,.08); }
.msg .who { font-weight:bold; font-size:12px; color:#1a73e8; }
.msg .time { font-size:11px; color:#999; float:right; margin-left:8px; }
.msg .text { font-size:15px; white-space:pre-wrap; word-break:break-word; }
.input { display:flex; border-top:1px solid #d5dbe1; padding:10px; background:#fff; }
.input input { flex:1; border:1px solid #c4ccd4; border-radius:6px; padding:10px; font-size:15px; }
.input button { margin-left:8px; border:0; background:#1a73e8; color:#fff; border-radius:6px; padding:0 18px; font-size:15px; cursor:pointer; }
.input button:hover { background:#1666c9; }
</style>
</head>
<body>
<div class="wrap">
  <aside class="side">
    <h3>В сети (<?php echo htmlspecialchars($user); ?>)</h3>
    <ul id="users"></ul>
  </aside>
  <div class="chat">
    <div class="msgs" id="msgs"></div>
    <form class="input" id="form" autocomplete="off">
      <input id="text" placeholder="Сообщение...">
      <button type="submit">Отправить</button>
    </form>
  </div>
</div>
<script>
var me = '<?php echo addcslashes($user, "'\\"); ?>';
var lastId = 0;
function poll(){
  var x = new XMLHttpRequest();
  x.open('GET','api.php?action=messages&after='+lastId+'&t='+Date.now());
  x.onload = function(){
    if(x.status===200){
      try { var d = JSON.parse(x.responseText); render(d); } catch(e){}
    }
  };
  x.send();
}
function render(d){
  if(d.messages){
    var box = document.getElementById('msgs');
    for(var i=0;i<d.messages.length;i++){
      var m = d.messages[i];
      if(m.id>lastId){ lastId = m.id; }
      var div = document.createElement('div');
      div.className = 'msg';
      var who = document.createElement('div');
      who.className = 'who';
      who.textContent = m.user + (m.user===me ? ' (вы)' : '');
      var time = document.createElement('span');
      time.className = 'time';
      time.textContent = m.time;
      who.appendChild(time);
      var text = document.createElement('div');
      text.className = 'text';
      text.textContent = m.text;
      div.appendChild(who);
      div.appendChild(text);
      box.appendChild(div);
    }
    box.scrollTop = box.scrollHeight;
  }
  if(d.users){
    var ul = document.getElementById('users');
    ul.innerHTML = '';
    for(var j=0;j<d.users.length;j++){
      var li = document.createElement('li');
      li.textContent = d.users[j];
      if(d.users[j]===me){ li.className = 'me'; }
      ul.appendChild(li);
    }
  }
}
document.getElementById('form').addEventListener('submit', function(e){
  e.preventDefault();
  var inp = document.getElementById('text');
  var v = inp.value;
  if(!v) return;
  var x = new XMLHttpRequest();
  x.open('POST','api.php');
  x.setRequestHeader('Content-Type','application/x-www-form-urlencoded');
  x.onload = function(){ inp.value=''; inp.focus(); poll(); };
  x.send('action=send&message='+encodeURIComponent(v));
});
setInterval(poll, 2000);
poll();
</script>
</body>
</html>