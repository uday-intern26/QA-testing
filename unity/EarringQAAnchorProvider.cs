using System;
using UnityEngine;

namespace AIJewel.QA
{
    /// <summary>
    /// Projects the earring attachment transforms into normalized viewport coordinates
    /// and publishes local as-worn offsets used for PASS tracking.
    /// Wire this to the attachment object, not the visual mesh center.
    /// Publish the JSON through window.__AIJEWEL_QA__ or GET /debug/tryon-state.
    /// </summary>
    public class EarringQAAnchorProvider : MonoBehaviour
    {
        public string jewelryId = "E123";
        public string jewelryType = "earring";
        public Transform leftAttachment;
        public Transform rightAttachment;
        public Camera tryOnCamera;

        [Serializable]
        public class SideAnchor
        {
            public float x;
            public float y;
            public bool visible;
            public float rotation;
            public float scale;
            public float local_x;
            public float local_y;
            public float local_z;
        }

        [Serializable]
        public class TryOnState
        {
            public long timestamp;
            public string jewelry_id;
            public string jewelry_type;
            public SideAnchor left;
            public SideAnchor right;
        }

        public TryOnState Capture()
        {
            Camera camera = tryOnCamera != null ? tryOnCamera : Camera.main;
            return new TryOnState
            {
                timestamp = DateTimeOffset.UtcNow.ToUnixTimeSeconds(),
                jewelry_id = jewelryId,
                jewelry_type = jewelryType,
                left = Project(camera, leftAttachment),
                right = Project(camera, rightAttachment)
            };
        }

        public string ToJson()
        {
            return JsonUtility.ToJson(Capture());
        }

        SideAnchor Project(Camera camera, Transform attachment)
        {
            if (camera == null || attachment == null)
            {
                return new SideAnchor { visible = false };
            }

            Vector3 screen = camera.WorldToScreenPoint(attachment.position);
            Vector3 local = attachment.localPosition;
            float width = Mathf.Max(1f, Screen.width);
            float height = Mathf.Max(1f, Screen.height);
            bool inFront = screen.z > 0f;
            return new SideAnchor
            {
                x = screen.x / width,
                y = 1f - (screen.y / height),
                visible = inFront && screen.x >= 0f && screen.x <= width && screen.y >= 0f && screen.y <= height,
                rotation = attachment.eulerAngles.z,
                scale = attachment.lossyScale.x,
                local_x = local.x,
                local_y = local.y,
                local_z = local.z
            };
        }
    }
}
