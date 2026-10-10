package com.mutsumi.focus.atomic;

import android.app.PendingIntent;
import android.content.Context;
import android.graphics.drawable.Icon;
import android.os.Bundle;

/** Wire fields verified against the supplied vivo demo and document 896. */
public final class VivoAtomicPayload {
    private VivoAtomicPayload() {}

    public static Bundle create(Context context, int iconResource, int operation,
            String scene, String title, String description, String timer,
            PendingIntent openIntent, boolean historicalIslandOnly, int record,
            String callbackToken) {
        Bundle extras = new Bundle();
        extras.putInt("notification.superx.operation", operation);
        extras.putBoolean("notification.superx.showNotify", true);
        extras.putInt("notification.superx.changedRecord", record);
        // This ROM resolves the activity key and checks eligibility before its
        // END branch. Retain the routing fields even for an end operation.
        if (historicalIslandOnly) {
            extras.putBoolean("notification.superx.islandNotify", true);
            if (operation == 2) {
                extras.putBundle("notification.superx.island", new Bundle());
                return extras;
            }
        } else {
            extras.putString("notification.superx.scene", scene);
            if (operation == 2) return extras;
        }

        Icon icon = Icon.createWithResource(context, iconResource);
        Bundle left = new Bundle();
        left.putParcelable("island.superx.leftInfo.icon", icon);
        left.putCharSequence("island.superx.leftInfo.content", title);
        Bundle right = new Bundle();
        right.putCharSequence("island.superx.rightInfo.content", timer);
        right.putParcelable("island.superx.rightInfo.clickResp", openIntent);
        Bundle island = new Bundle();
        island.putInt("island.superx.leftTemplate", 1);
        island.putBundle("island.superx.leftInfo", left);
        island.putInt("island.superx.rightTemplate", 4);
        island.putBundle("island.superx.rightInfo", right);
        island.putInt("island.superx.islandClick", 1);
        island.putParcelable("island.superx.clickResp", openIntent);
        island.putInt("island.superx.showTime", 180);
        island.putString("island.superx.callbackInfos", callbackToken);
        extras.putBundle("notification.superx.island", island);

        if (historicalIslandOnly) {
            // Supplied release1.5 PDF pp.7-9 documents this older path without
            // scene/template/card fields. Current public doc omits the flag.
            // It is a firmware experiment, not proof of a permission bypass.
            return extras;
        }

        extras.putInt("notification.superx.template", 1);
        extras.putParcelable("notification.superx.clickResp", openIntent);
        extras.putBoolean("notification.superx.sound", false);

        Bundle base = new Bundle();
        base.putParcelable("notification.superx.baseInfos.icon", icon);
        base.putCharSequence("notification.superx.baseInfos.title", title);
        base.putCharSequence("notification.superx.baseInfos.content", description);
        extras.putBundle("notification.superx.baseInfos", base);

        Bundle info = new Bundle();
        info.putString("notification.superx.infos.describe", description);
        info.putString("notification.superx.infos.coreInfo", timer);
        info.putParcelable("notification.superx.infos.image", icon);
        info.putParcelable("notification.superx.infos.imageClickResp", openIntent);
        extras.putBundle("notification.superx.infos", info);

        Bundle shortInfo = new Bundle();
        shortInfo.putParcelable("notification.superx.shortInfos.image", icon);
        shortInfo.putParcelable("notification.superx.shortInfos.icon", icon);
        shortInfo.putString("notification.superx.shortInfos.coreInfoShort", timer);
        shortInfo.putString("notification.superx.shortInfos.describeShort", description);
        extras.putBundle("notification.superx.shortInfos", shortInfo);

        Bundle capsule = new Bundle();
        capsule.putInt("notification.superx.capsule.state", 1);
        capsule.putParcelable("notification.superx.capsule.icon", icon);
        capsule.putString("notification.superx.capsule.content", timer);
        capsule.putParcelable("notification.superx.capsule.clickResp", openIntent);
        extras.putBundle("notification.superx.capsule", capsule);
        return extras;
    }
}
