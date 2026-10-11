package com.mutsumi.focus.atomiclab;

import android.Manifest;
import android.app.Activity;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageManager;
import android.content.pm.PermissionInfo;
import android.graphics.Typeface;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.provider.Settings;
import android.service.notification.StatusBarNotification;
import android.util.Log;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Spinner;
import android.widget.ArrayAdapter;

import com.mutsumi.focus.atomic.VivoAtomicPayload;

import java.io.FileOutputStream;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Arrays;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;

public class AtomicLabActivity extends Activity {
    private static final String TAG = "MutsumiAtomicLab";
    private static final String CHANNEL = "atomic_lab_v1";
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Map<Integer, Trial> trials = new LinkedHashMap<>();
    private NotificationManager manager;
    private EditText sceneInput;
    private TextView output;
    private Spinner layoutSelector;
    private BroadcastReceiver receiver;
    private long loopUntil;

    private static final class Trial {
        final String mode, scene, layout, token = UUID.randomUUID().toString();
        final long started = SystemClock.elapsedRealtime();
        int record;
        Trial(String mode, String scene) { this(mode, scene, null); }
        Trial(String mode, String scene, String layout) { this.mode = mode; this.scene = scene; this.layout = layout; }
    }

    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        manager = getSystemService(NotificationManager.class);
        NotificationChannel channel = new NotificationChannel(CHANNEL, "原子岛协议实验", NotificationManager.IMPORTANCE_HIGH);
        channel.setSound(null, null);
        channel.enableVibration(false);
        manager.createNotificationChannel(channel);
        buildUi();
        registerCallbacks();
        log("设备 " + Build.MANUFACTURER + " / " + Build.MODEL + " / Android " + Build.VERSION.RELEASE + " API " + Build.VERSION.SDK_INT);
        log("包名 " + getPackageName() + "；独立实验，无账号和网络连接");
        log("notify() 返回或活动通知存在，仅说明已发送；请观察原子岛并核对系统回执。");
        applyCommand(getIntent());
    }

    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        applyCommand(intent);
    }

    private void buildUi() {
        LinearLayout body = new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL);
        int pad = (int) (16 * getResources().getDisplayMetrics().density);
        body.setPadding(pad, pad * 2, pad, pad);
        TextView title = new TextView(this);
        title.setText("Mutsumi 原子岛实验");
        title.setTextSize(24);
        body.addView(title);
        TextView note = new TextView(this);
        note.setText("用于自己的设备。先发普通通知，再比较全模板、历史岛路径和 Android 实时通知。实验不会自动修改系统白名单。结束会移除本应用的实验通知。");
        body.addView(note);
        sceneInput = new EditText(this);
        sceneInput.setSingleLine(true);
        sceneInput.setText("FOCUS_TIMER");
        sceneInput.setHint("scene（可手动对比官方 demo 的 TAKEOUT）");
        body.addView(sceneInput);
        layoutSelector = new Spinner(this);
        layoutSelector.setAdapter(new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, VivoLayoutSamples.LABELS));
        body.addView(layoutSelector);
        button(body, "发送选择的版式（点击或长按岛看卡片）", () -> createLayout(VivoLayoutSamples.KEYS[layoutSelector.getSelectedItemPosition()]));
        button(body, "通知设置 / 申请通知权限", this::permissions);
        button(body, "读取场景开关和隐藏接口", this::probe);
        button(body, "读取本应用通知的系统分类结果", this::inspectOwnNotifications);
        button(body, "普通通知（对照）", () -> createTrial("plain"));
        button(body, "原子通知：完整模板 + 岛 + 胶囊", () -> createTrial("full"));
        button(body, "历史 PDF 岛路径：islandNotify=true", () -> createTrial("island"));
        button(body, "Android 16 实时通知（对照）", () -> createTrial("android"));
        button(body, "更新已创建通知", this::updateTrials);
        button(body, "每 15 秒更新，3 分钟后自动结束", this::startLoop);
        button(body, "结束并清理实验通知", this::endTrials);
        button(body, "仅发送 END（协议结束对照）", this::protocolEndTrials);
        output = new TextView(this);
        output.setTextIsSelectable(true);
        output.setTypeface(Typeface.MONOSPACE);
        output.setTextSize(12);
        body.addView(output);
        ScrollView scroll = new ScrollView(this);
        scroll.addView(body);
        scroll.setOnApplyWindowInsetsListener((view, insets) -> {
            body.setPadding(pad + insets.getSystemWindowInsetLeft(), pad + insets.getSystemWindowInsetTop(),
                    pad + insets.getSystemWindowInsetRight(), pad + insets.getSystemWindowInsetBottom());
            return insets;
        });
        setContentView(scroll);
    }

    private void button(LinearLayout body, String text, Runnable action) {
        Button button = new Button(this);
        button.setText(text);
        button.setAllCaps(false);
        button.setOnClickListener(view -> action.run());
        body.addView(button);
    }

    private void permissions() {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[] { Manifest.permission.POST_NOTIFICATIONS }, 1);
        } else {
            startActivity(new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, getPackageName()));
        }
    }

    private void probe() {
        String scene = sceneInput.getText().toString().trim();
        log("通知已开启=" + manager.areNotificationsEnabled() + "; scene=" + scene);
        try {
            Method getter = NotificationManager.class.getMethod("getSceneStatus", String.class, String.class);
            log("getSceneStatus=" + getter.invoke(manager, getPackageName(), scene) + "（场景开关，不等同厂商授权）");
        } catch (ReflectiveOperationException | SecurityException error) { failure("getSceneStatus", error); }
        try {
            Method setter = NotificationManager.class.getMethod("setSuperXInfosSceneList", List.class, List.class, List.class, List.class);
            log("发现 " + setter.toGenericString() + "；未调用，需先核实权限检查和列表是否整体替换。");
        } catch (ReflectiveOperationException | SecurityException error) { failure("setSuperXInfosSceneList 可见性", error); }
        for (Method method : NotificationManager.class.getDeclaredMethods()) {
            String name = method.getName().toLowerCase(Locale.ROOT);
            if (name.contains("superx") || name.contains("island") || name.contains("scenestatus")) log("接口 " + method.toGenericString());
        }
        if (Build.VERSION.SDK_INT >= 36) log("Android 实时通知推广开关=" + manager.canPostPromotedNotifications());
        try {
            PermissionInfo permission = getPackageManager().getPermissionInfo("com.vivo.notification.ISLAND_NOTI_SUPPORT", 0);
            log("仅岛权限 protectionLevel=" + permission.protectionLevel + "; 本应用获权=" +
                    (checkSelfPermission(permission.name) == PackageManager.PERMISSION_GRANTED));
        } catch (PackageManager.NameNotFoundException error) { failure("仅岛权限定义", error); }
        try {
            Method version = NotificationManager.class.getMethod("getSuperXVersion");
            log("SuperX 协议版本=" + version.invoke(manager));
        } catch (ReflectiveOperationException | SecurityException error) { failure("getSuperXVersion", error); }
        inspectOwnNotifications();
    }

    private void inspectOwnNotifications() {
        StatusBarNotification[] own = manager.getActiveNotifications();
        if (own.length == 0) log("本应用没有活动通知。");
        for (StatusBarNotification sbn : own) {
            Notification notification = sbn.getNotification();
            Object marker = notification.extras.get("SUPERX_VALUE");
            log("本应用系统记录 id=" + sbn.getId() + "; SUPERX_VALUE=" + marker + "; flags=0x" + Integer.toHexString(notification.flags));
        }
    }

    private void createTrial(String mode) {
        if (!manager.areNotificationsEnabled()) { log("通知权限未开启，请先授权。"); permissions(); return; }
        if ("android".equals(mode) && Build.VERSION.SDK_INT < 36) { log("Android 对照需要 API 36。"); return; }
        int id = idFor(mode);
        Trial old = trials.remove(id);
        if (old != null) { publish(id, old, 2); VivoAtomicPayload.cancel(manager, id); }
        Trial trial = new Trial(mode, sceneInput.getText().toString().trim());
        if ("full".equals(mode) && trial.scene.isEmpty()) { log("全模板需要填写 scene。"); return; }
        trials.put(id, trial);
        publish(id, trial, 0);
    }

    private static int idFor(String mode) {
        return switch (mode) { case "full" -> 9402; case "island" -> 9403; case "android" -> 9404; default -> 9401; };
    }

    private void createLayout(String key) {
        VivoLayoutSamples.label(key);
        if (!manager.areNotificationsEnabled()) { permissions(); return; }
        endTrials();
        Trial trial = new Trial("full", sceneInput.getText().toString().trim(), key);
        trials.put(9405, trial);
        log("版式 " + key + "：" + VivoLayoutSamples.label(key));
        publish(9405, trial, 0);
    }

    private void publish(int id, Trial trial, int operation) {
        if (operation == 2 && ("plain".equals(trial.mode) || "android".equals(trial.mode))) { manager.cancel(id); return; }
        long seconds = (SystemClock.elapsedRealtime() - trial.started) / 1000;
        String timer = String.format(Locale.ROOT, "%02d:%02d", seconds / 60, seconds % 60);
        PendingIntent open = PendingIntent.getActivity(this, id,
                new Intent(this, AtomicLabActivity.class).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        Notification.Builder builder = new Notification.Builder(this, CHANNEL)
                .setSmallIcon(R.drawable.ic_atomic_lab).setContentTitle("专注协议实验 · " + trial.mode)
                .setContentText(timer + " · " + trial.scene).setContentIntent(open)
                .setOnlyAlertOnce(true).setOngoing(operation != 2);
        if ("full".equals(trial.mode) || "island".equals(trial.mode)) {
            Bundle payload = VivoAtomicPayload.create(this, R.drawable.ic_atomic_lab, operation,
                    trial.scene, "专注实验", "本地学习计时", timer, open,
                    "island".equals(trial.mode), ++trial.record, trial.token);
            if (trial.layout != null && operation != 2) VivoLayoutSamples.apply(this, payload, open, trial.layout);
            builder.addExtras(payload);
        } else if ("android".equals(trial.mode) && Build.VERSION.SDK_INT >= 36) {
            builder.setCategory(Notification.CATEGORY_PROGRESS)
                    .setStyle(new Notification.ProgressStyle().setProgressIndeterminate(true).setStyledByProgress(true));
            Bundle request = new Bundle();
            request.putBoolean("android.requestPromotedOngoing", true);
            builder.addExtras(request);
        }
        try {
            manager.notify(id, builder.build());
            log("已发送 id=" + id + " mode=" + trial.mode + " operation=" + operation + " record=" + trial.record + " timer=" + timer);
        } catch (RuntimeException error) { failure("发送 " + id, error); }
    }

    private void updateTrials() {
        if (trials.isEmpty()) { log("请先创建实验通知。"); return; }
        for (Map.Entry<Integer, Trial> item : trials.entrySet()) publish(item.getKey(), item.getValue(), 1);
    }

    private final Runnable loop = new Runnable() {
        @Override public void run() {
            if (SystemClock.elapsedRealtime() >= loopUntil) { endTrials(); log("3 分钟维护实验已结束。"); return; }
            updateTrials();
            handler.postDelayed(this, 15_000);
        }
    };

    private void startLoop() {
        if (trials.isEmpty()) { log("请先创建实验通知。"); return; }
        handler.removeCallbacks(loop);
        loopUntil = SystemClock.elapsedRealtime() + 180_000;
        handler.postDelayed(loop, 15_000);
        log("开始 3 分钟维护：15 秒更新一次，结束后清理。");
    }

    private void endTrials() {
        handler.removeCallbacks(loop);
        for (Map.Entry<Integer, Trial> item : trials.entrySet()) { publish(item.getKey(), item.getValue(), 2); VivoAtomicPayload.cancel(manager, item.getKey()); }
        trials.clear();
        for (int id = 9401; id <= 9405; id++) VivoAtomicPayload.cancel(manager, id);
        log("已结束本应用的实验通知。");
    }

    private void protocolEndTrials() {
        handler.removeCallbacks(loop);
        for (Map.Entry<Integer, Trial> item : trials.entrySet()) publish(item.getKey(), item.getValue(), 2);
        trials.clear();
        log("仅发送 END，未额外 cancel；请读取本应用系统记录核验。");
    }

    private void registerCallbacks() {
        receiver = new BroadcastReceiver() {
            @Override public void onReceive(Context context, Intent intent) {
                if ("android.app.action.SUPERX_STATE".equals(intent.getAction())) {
                    log("SUPERX_STATE 回执=" + intent.getBooleanExtra("SUPERX_STATE", false) + "（同包状态，需与系统记录核对）");
                    return;
                }
                Bundle info = intent.getBundleExtra("islandInfo");
                if (info == null) return;
                String token = info.getString("island.superx.callbackInfos", "");
                for (Map.Entry<Integer, Trial> item : trials.entrySet()) {
                    if (item.getValue().token.equals(token)) {
                        log("岛回执 id=" + item.getKey() + " state=" + info.getInt("island.superx.state", -1) + "（需与实际画面核对）");
                        return;
                    }
                }
            }
        };
        IntentFilter filter = new IntentFilter("vivo.intent.action.ISLAND_STATE_CHANGED");
        filter.addAction("android.app.action.SUPERX_STATE");
        registerReceiver(receiver, filter, Context.RECEIVER_EXPORTED);
    }

    private void applyCommand(Intent intent) {
        String scene = intent.getStringExtra("scene");
        if (scene != null) sceneInput.setText(scene);
        String action = intent.getStringExtra("action");
        if (action == null) return;
        switch (action) {
            case "probe" -> probe();
            case "inspect" -> inspectOwnNotifications();
            case "create" -> {
                String mode = intent.getStringExtra("mode");
                if (Arrays.asList("plain", "full", "island", "android").contains(mode == null ? "" : mode)) createTrial(mode);
                else log("未知实验模式。");
            }
            case "update" -> updateTrials();
            case "layout" -> createLayout(intent.getStringExtra("layout"));
            case "loop" -> startLoop();
            case "end" -> endTrials();
            case "protocolEnd" -> protocolEndTrials();
            default -> log("未知实验动作。");
        }
    }

    private void failure(String action, Throwable error) {
        Throwable cause = error instanceof InvocationTargetException && error.getCause() != null ? error.getCause() : error;
        log(action + ": " + cause.getClass().getSimpleName() + ": " + cause.getMessage());
        Log.e(TAG, action, cause);
    }

    private void log(String message) {
        Log.i(TAG, message);
        String line = System.currentTimeMillis() + " " + message + "\n";
        output.append(line);
        if (output.length() > 24_000) output.setText(output.getText().subSequence(output.length() - 16_000, output.length()));
        try (FileOutputStream file = openFileOutput("atomic-lab.log", MODE_APPEND)) { file.write(line.getBytes(StandardCharsets.UTF_8)); }
        catch (java.io.IOException error) { Log.e(TAG, "Writing local experiment log", error); }
    }

    @Override public void onDestroy() {
        endTrials();
        if (receiver != null) unregisterReceiver(receiver);
        super.onDestroy();
    }
}
