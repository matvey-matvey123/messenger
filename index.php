<?php
session_start();
if (isset($_POST['name'])) {
    $name = trim($_POST['name']);
    if ($name !== '') {
        $_SESSION['user'] = mb_substr($name, 0, 20);
        header('Location: chat.php');
        exit;
    }
}
?>
<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Вход в мессенджер</title>
<style>
body { font-family:'Segoe UI',Arial,sans-serif; display:flex; align-items:center; justify-content:center; height:100vh; margin:0; background:#e9eef3; }
.card { background:#fff; padding:28px; border-radius:10px; box-shadow:0 2px 10px rgba(0,0,0,.1); width:280px; }
h1 { font-size:20px; margin:0 0 16px; color:#333; }
input { width:100%; box-sizing:border-box; border:1px solid #c4ccd4; border-radius:6px; padding:10px; font-size:15px; margin-bottom:12px; }
button { width:100%; border:0; background:#1a73e8; color:#fff; border-radius:6px; padding:11px; font-size:15px; cursor:pointer; }
button:hover { background:#1666c9; }
</style>
</head>
<body>
<form class="card" method="post">
  <h1>Мессенджер</h1>
  <input name="name" maxlength="20" placeholder="Ваш ник" required autofocus>
  <button type="submit">Войти</button>
</form>
</body>
</html>