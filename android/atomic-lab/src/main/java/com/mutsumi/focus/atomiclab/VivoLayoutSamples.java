package com.mutsumi.focus.atomiclab;

import android.app.PendingIntent;
import android.content.Context;
import android.graphics.Color;
import android.graphics.drawable.Icon;
import android.os.Bundle;

import java.util.ArrayList;
import java.util.Arrays;

/** Document 896's public local templates, isolated from the actual timer. */
final class VivoLayoutSamples {
    static final String[] KEYS = { "c1", "c2", "c3", "c4", "c5",
            "r1", "r2", "r3", "r4", "r5", "r6",
            "b0", "b1", "b2", "b3", "b4", "b5", "b6" };
    static final String[] LABELS = { "卡片 1：强调信息", "卡片 2：节点进度", "卡片 3：左右对称",
            "卡片 4：基础信息", "卡片 5：导航样例",
            "岛右侧 1：律动", "岛右侧 2：进度环", "岛右侧 3：加载",
            "岛右侧 4：文字 + 图标", "岛右侧 5：图标 + 文字", "岛右侧 6：胶囊文字",
            "基础辅助 0：无", "基础辅助 1：文字", "基础辅助 2：胶囊",
            "基础辅助 3：图片", "基础辅助 4：多图片", "基础辅助 5：进度", "基础辅助 6：加载" };

    static String label(String key) {
        int index = Arrays.asList(KEYS).indexOf(key);
        if (index < 0) throw new IllegalArgumentException("Unknown layout: " + key);
        return LABELS[index];
    }

    static void apply(Context context, Bundle extras, PendingIntent click, String key) {
        String label = label(key);
        int number = Integer.parseInt(key.substring(1));
        int template = key.startsWith("c") ? number : key.startsWith("b") ? 4 : 1;
        int rightTemplate = key.startsWith("r") ? number : 4;
        Icon clock = Icon.createWithResource(context, R.drawable.ic_atomic_lab);
        Icon check = Icon.createWithResource(context, R.drawable.ic_sample_check);
        Icon arrow = Icon.createWithResource(context, R.drawable.ic_sample_arrow);
        int accent = Color.rgb(110, 221, 185);
        Bundle base = extras.getBundle("notification.superx.baseInfos");
        base.putCharSequence("notification.superx.baseInfos.title", label);
        base.putCharSequence("notification.superx.baseInfos.content", "本地版式样例 · 非真实订单或导航");
        base.putInt("notification.superx.baseInfos.subInfo", key.startsWith("b") ? number : 0);
        base.putString("notification.superx.baseInfos.subText", "25 分钟");
        base.putInt("notification.superx.baseInfos.subTextColor", Color.BLACK);
        base.putInt("notification.superx.baseInfos.subCapsuleBgColor", accent);
        base.putParcelable("notification.superx.baseInfos.subImage", check);
        base.putParcelable("notification.superx.baseInfos.subInfoClickResp", click);
        base.putParcelableArrayList("notification.superx.baseInfos.subImageList",
                new ArrayList<>(Arrays.asList(clock, check, arrow)));
        base.putParcelableArrayList("notification.superx.baseInfos.subInfoClickRespList",
                new ArrayList<>(Arrays.asList(click, click, click)));
        base.putInt("notification.superx.baseInfos.subProgress", 65);
        base.putInt("notification.superx.baseInfos.subProgressColor", accent);
        base.putInt("notification.superx.baseInfos.subProgressBgColor", 0x33555555);
        base.putInt("notification.superx.baseInfos.progressState", 0);
        base.putString("notification.superx.baseInfos.progressContent", "65%");
        base.putInt("notification.superx.baseInfos.loadingColor", accent);

        Bundle info = new Bundle();
        info.putString("notification.superx.infos.describe", "本地计时样例");
        info.putString("notification.superx.infos.coreInfo", "25:00");
        info.putParcelable("notification.superx.infos.image", clock);
        info.putParcelable("notification.superx.infos.imageClickResp", click);
        info.putParcelableArrayList("notification.superx.infos.nodeIcon",
                new ArrayList<>(Arrays.asList(clock, check, arrow)));
        info.putInt("notification.superx.infos.progress", 65);
        info.putInt("notification.superx.infos.progressColor", accent);
        info.putInt("notification.superx.infos.BgColor", 0x33555555);
        info.putParcelable("notification.superx.infos.indicatorIcon", check);
        info.putInt("notification.superx.infos.indicatorLoc", 2);
        info.putString("notification.superx.infos.leftMain", "09:00");
        info.putString("notification.superx.infos.leftSub", "计划开始");
        info.putInt("notification.superx.infos.midMainType", 2);
        info.putString("notification.superx.infos.midMainMsg", "25 分钟");
        info.putInt("notification.superx.infos.midSubType", 2);
        info.putString("notification.superx.infos.midSubMsg", "专注样例");
        info.putString("notification.superx.infos.rightMain", "09:25");
        info.putString("notification.superx.infos.rightSub", "计划完成");
        info.putParcelable("notification.superx.infos.navIcon", arrow);
        info.putString("notification.superx.infos.navMsg", "版式演示#进入下一阶段");
        extras.putInt("notification.superx.template", template);
        extras.putBundle("notification.superx.infos", info);

        Bundle island = extras.getBundle("notification.superx.island");
        island.getBundle("island.superx.leftInfo").putCharSequence(
                "island.superx.leftInfo.content", key.startsWith("r") ? "岛版式 " + number : "卡片样例");
        Bundle right = new Bundle();
        right.putIntegerArrayList("island.superx.rightInfo.waveColor",
                new ArrayList<>(Arrays.asList(accent, Color.WHITE)));
        right.putInt("island.superx.rightInfo.waveState", 1);
        right.putInt("island.superx.rightInfo.progressValue", 65);
        right.putInt("island.superx.rightInfo.progressColor", accent);
        right.putInt("island.superx.rightInfo.progressBgColor", 0xFF555555);
        right.putInt("island.superx.rightInfo.progressState", 0);
        right.putInt("island.superx.rightInfo.loadingColor", accent);
        right.putParcelable("island.superx.rightInfo.icon", check);
        right.putCharSequence("island.superx.rightInfo.content", "25:00");
        right.putCharSequence("island.superx.rightInfo.capsuleContent", "继续");
        right.putInt("island.superx.rightInfo.capsuleBgColor", accent);
        right.putParcelable("island.superx.rightInfo.clickResp", click);
        island.putInt("island.superx.rightTemplate", rightTemplate);
        island.putBundle("island.superx.rightInfo", right);
        island.putInt("island.superx.islandClick", 0);
        island.putBoolean("island.superx.forceShowCard", !key.startsWith("r"));
        island.putInt("island.superx.template", template);
        island.putBundle("island.superx.baseInfos", new Bundle(base));
        island.putBundle("island.superx.infos", new Bundle(info));
        extras.getBundle("notification.superx.shortInfos").putString(
                "notification.superx.shortInfos.describeShort", label);
    }
}
