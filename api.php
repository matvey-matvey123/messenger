<?php
session_start();
date_default_timezone_set('UTC');

$dir = __DIR__;
$msgFile = $dir . '/messages.json';
$userFile = $dir . '/users.json';

$action = isset($_REQUEST['action']) ? $_REQUEST['action'] : '';
$user = isset($_SESSION['user']) ? $_SESSION['user'] : '';

function readJson($file) {
    if (!file_exists($file)) return array();
    $raw = @file_get_contents($file);
    $data = json_decode($raw, true);
    return is_array($data) ? $data : array();
}

function writeJson($file, $data) {
    $fp = @fopen($file, 'c+');
    if ($fp === false) return false;
    if (!flock($fp, LOCK_EX)) { fclose($fp); return false; }
    ftruncate($fp, 0);
    rewind($fp);
    fwrite($fp, json_encode($data));
    fflush($fp);
    flock($fp, LOCK_UN);
    fclose($fp);
    return true;
}

function touchUser($userFile, $user) {
    $users = readJson($userFile);
    $users[$user] = time();
    $now = time();
    foreach ($users as $u => $seen) {
        if ($seen < $now - 15) unset($users[$u]);
    }
    writeJson($userFile, $users);
}

$out = array();
if ($user === '') {
    $out['error'] = 'no-session';
} else {
    touchUser($userFile, $user);
    if ($action === 'send') {
        $text = isset($_REQUEST['message']) ? trim($_REQUEST['message']) : '';
        if ($text !== '') {
            $text = mb_substr($text, 0, 1000);
            $fp = @fopen($msgFile, 'c+');
            if ($fp !== false) {
                if (flock($fp, LOCK_EX)) {
                    $messages = json_decode(stream_get_contents($fp), true);
                    if (!is_array($messages)) $messages = array();
                    $id = 1;
                    foreach ($messages as $m) {
                        if (isset($m['id']) && $m['id'] >= $id) $id = $m['id'] + 1;
                    }
                    $messages[] = array('id' => $id, 'user' => $user, 'text' => $text, 'ts' => time());
                    ftruncate($fp, 0);
                    rewind($fp);
                    fwrite($fp, json_encode($messages));
                    fflush($fp);
                    flock($fp, LOCK_UN);
                }
                fclose($fp);
            }
        }
    } elseif ($action === 'messages') {
        $after = isset($_REQUEST['after']) ? max(0, intval($_REQUEST['after'])) : 0;
        $all = readJson($msgFile);
        $new = array();
        foreach ($all as $m) {
            if (isset($m['id']) && $m['id'] > $after) {
                $new[] = array(
                    'id' => $m['id'],
                    'user' => $m['user'],
                    'text' => $m['text'],
                    'time' => date('H:i', $m['ts'])
                );
            }
        }
        $out['messages'] = $new;
        $users = readJson($userFile);
        $names = array();
        foreach ($users as $u => $seen) { $names[] = $u; }
        natsort($names);
        $out['users'] = array_values($names);
    } else {
        $out['error'] = 'unknown-action';
    }
}

header('Content-Type: application/json; charset=utf-8');
echo json_encode($out, JSON_UNESCAPED_UNICODE);