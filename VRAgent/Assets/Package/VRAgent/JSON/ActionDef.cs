using System.Collections.Generic;
using Unity.Plastic.Newtonsoft.Json;
using UnityEngine;

namespace HenryLab.VRAgent
{
    [JsonConverter(typeof(ActionUnitConverter))] // ֧��JSON��̬
    public class ActionUnit
    {
        public string type;
        [JsonProperty("source_object_fileID")] public string objectA;

        // v2.2: sequential-dependency metadata. Preserved through serialization
        // but NOT consumed at execution time — VerifierAgent validates these
        // statically before the test plan is run.
        [JsonProperty("depends_on_task_index")] public List<int>? dependsOnTaskIndex;
        [JsonProperty("required_state_changes")] public List<string>? requiredStateChanges;
        [JsonProperty("produced_state_changes")] public List<string>? producedStateChanges;
    }

    public class GrabActionUnit : ActionUnit
    {
        [JsonProperty("target_object_fileID")] public string? objectB;
        [JsonProperty("target_position")] public Vector3? targetPosition;
    }



    public class TriggerActionUnit : ActionUnit
    {
        [JsonProperty("triggerring_time")] public float? trigerringTime;
        [JsonProperty("triggerring_events")] public List<eventUnit> triggerringEvents;
        [JsonProperty("triggerred_events")] public List<eventUnit> triggerredEvents;
    }

    /// <summary>
    /// TransformActionUnit �������������ƽ��/��ת/���Ų���
    /// </summary>
    public class TransformActionUnit : TriggerActionUnit
    {
        [JsonProperty("delta_position")] public Vector3 deltaPosition;
        [JsonProperty("delta_rotation")] public Vector3 deltaRotation;
        [JsonProperty("delta_scale")] public Vector3 deltaScale;
    }

    public class MoveActionUnit : ActionUnit
    {
        [JsonProperty("target_object_fileID")] public string? objectB;
        [JsonProperty("target_position")] public Vector3? targetPosition;
    }

    public class SocketActionUnit : ActionUnit
    {
        [JsonProperty("socket_mode")] public string socketMode; // "insert" or "remove"
        // Optional: the interactable object being inserted/removed (as a scene FileID).
        // When provided, SocketAction will populate SelectEnter/ExitEventArgs.interactableObject
        // so socket receivers can validate the inserted object.
        [JsonProperty("inserted_object_fileID")] public string? insertedObjectFileId;
    }
}
