using HenryLab.VRExplorer;
using System;
using System.Collections.Generic;
using System.IO;
using System.Threading.Tasks;
using Unity.Plastic.Newtonsoft.Json;
using UnityEditor;
using UnityEngine;

namespace HenryLab.VRAgent
{
    public class VRAgent : BaseExplorer
    {
        private class TestPlanCounter
        {
            public int taskUnitCount = 0, actionUnitCount = 0;
            public int grabCount = 0, transformCount = 0, triggerCount = 0, socketCount = 0;
            public int objCount = 0, hitObjCount = 0;
            public int componentCount = 0, hitComponentCount = 0;

            public void Log()
            {
                // ====== Debug ��� ======
                Debug.Log(
                    $"{Str.Tags.LogsTag} Test Plan Metrics:\n" +
                    new RichText().Add($"Tasks: {taskUnitCount}, Actions: {actionUnitCount}\n", color: Color.yellow, bold: true) +
                    new RichText().Add($"Grab: {grabCount}, Trigger: {triggerCount}, Transform: {transformCount}, Socket: {socketCount}\n", color: Color.yellow, bold: true) +
                    new RichText().Add($"Objects: {objCount}, HitObjects: {hitObjCount}\n", color: Color.yellow, bold: true) +
                    new RichText().Add($"Components: {componentCount}, HitComponents: {hitComponentCount}", color: Color.yellow, bold: true)
                );
            }
        }

        private int _index = 0;
        private TestPlanCounter _testPlanCounter;
        private List<TaskUnit> _taskUnits = new List<TaskUnit>();

        [Header("Show for Debug")]
        [SerializeField] private GameObject objA;

        [SerializeField] private GameObject objB;

        public bool useFileID = true;

        private static FileIDContainer GetOrCreateManager()
        {
            FileIDContainer manager = FindObjectOfType<FileIDContainer>();
            if(manager == null)
            {
                GameObject go = new GameObject("FileIdManager");
                manager = go.AddComponent<FileIDContainer>();
                Debug.Log("Created FileIdManager in scene");
            }
            return manager;
        }

        protected TaskUnit NextTask => _taskUnits[_index++];

        #region ������Ϊִ�еĳ���̽����Scene Exploration with Behaviour Executation��

        /// <summary>
        /// �ظ�ִ�г���̽����
        /// ��ʼʱ��¼������Ϣ������������ʱ�Զ������첽����
        /// </summary>
        /// <returns></returns>
        protected override async Task RepeatSceneExplore()
        {
            ExperimentManager.Instance.StartRecording();
            //StoreMonoPos();
            while(!_applicationQuitting)
            {
                await SceneExplore();
                //ExperimentManager.Instance.ShowMetrics();
                for(int i = 0; i < 30; i++)
                {
                    await Task.Yield();
                }
                if(TestFinished)
                {
                    //ExperimentManager.Instance.ExperimentFinish();
                    if(exitAfterTesting)
                    {
                        UnityEditor.EditorApplication.isPlaying = false;
                    }
                    else
                    {
                        // ʵ������� ��ѡ���˳�����������״̬ѭ��ʵ��
                        ResetExploration();
                    }
                }
            }
        }

        protected override async Task SceneExplore()
        {
            if(!TestFinished)
            {
                await TaskExecutation();
            }
        }

        protected override async Task TaskExecutation()
        {
            _curTask = TaskGenerator(NextTask);

            foreach(var action in _curTask)
            {
                try
                {
                    await action.Execute();
                }
                catch(Exception ex)
                {
                    Debug.LogException(ex);
                }
            }
        }

        protected override void ResetExploration()
        {
        }

        protected override bool TestFinished => _index >= _taskUnits.Count;

        #endregion ������Ϊִ�еĳ���̽����Scene Exploration with Behaviour Executation��

        private static TaskList GetTaskListFromJson()
        {
            string filePath = PlayerPrefs.GetString("TestPlanPath", Str.TestPlanPath);
            if(!File.Exists(filePath))
            {
                Debug.LogError($"Test plan file not found at: {filePath}");
                return null;
            }

            try
            {
                string jsonContent = File.ReadAllText(filePath);
                // TaskList taskList = JsonUtility.FromJson<TaskList>(jsonContent);  ��֧�ֶ�̬
                TaskList taskList = JsonConvert.DeserializeObject<TaskList>(jsonContent);
                if(taskList == null)
                {
                    Debug.LogError("Failed to parse test plan JSON");
                }
                return taskList;
            }
            catch(Exception e)
            {
                Debug.LogError($"Failed to import test plan: {e.Message}\n{e.StackTrace}");
            }
            return null;
        }

        /// <summary>
        /// ������Լƻ�
        /// </summary>
        /// <param name="useFileID"></param>
        public static void ImportTestPlan(bool useFileID = true)
        {
            TaskList tasklist = GetTaskListFromJson();
            if(tasklist == null) return;

            FileIDContainer manager = GetOrCreateManager();
            manager.Clear();

            // ====== ͳ����Ϣ ======
            TestPlanCounter counter = new TestPlanCounter();
            counter.taskUnitCount = tasklist.taskUnits.Count;

            foreach(var taskUnit in tasklist.taskUnits)
            {
                foreach(var action in taskUnit.actionUnits)
                {
                    counter.actionUnitCount++;
                    if(!string.IsNullOrEmpty(action.objectA)) counter.objCount++;



                    switch(action.type)
                    {
                        case "Grab":
                        {
                            GameObject objA = FileIDResolver.FindGameObject(action.objectA, useFileID);
                            if(objA != null)
                            {
                                counter.hitObjCount++;
                                manager.Add(action.objectA, objA);
                            }

                            counter.grabCount++;
                            GrabActionUnit grabAction = action as GrabActionUnit;
                            if(grabAction != null && !string.IsNullOrEmpty(grabAction.objectB))
                            {
                                counter.objCount++;
                                GameObject objB = FileIDResolver.FindGameObject(grabAction.objectB, useFileID);
                                if(objB != null)
                                {
                                    counter.hitObjCount++;
                                    manager.Add(grabAction.objectB, objB);
                                }
                            }
                        }
                        break;


                        case "Trigger":
                        {
                            GameObject objA = FileIDResolver.FindGameObject(action.objectA, useFileID);
                            if(objA != null)
                            {
                                counter.hitObjCount++;
                                manager.Add(action.objectA, objA);
                            }

                            counter.triggerCount++;
                            TriggerActionUnit triggerAction = action as TriggerActionUnit;
                            if(triggerAction != null)
                            {
                                manager.AddComponents(triggerAction.triggerringEvents, ref counter.componentCount, ref counter.hitComponentCount);
                                manager.AddComponents(triggerAction.triggerredEvents, ref counter.componentCount, ref counter.hitComponentCount);
                            }
                        }
                        break;

                        case "Transform":
                        counter.transformCount++;
                        break;


                        case "Move":
                        MoveActionUnit moveAction = action as MoveActionUnit;
                        if(!string.IsNullOrEmpty(moveAction.objectB))
                        {
                            counter.objCount++;
                            GameObject objB = FileIDResolver.FindGameObject(moveAction.objectB, useFileID);
                            if(objB != null)
                            {
                                counter.hitObjCount++;
                                manager.Add(moveAction.objectB, objB);
                            }
                        }
                        break;

                        case "Socket":
                        {
                            counter.socketCount++;
                            GameObject objA = FileIDResolver.FindGameObject(action.objectA, useFileID);
                            if(objA != null)
                            {
                                counter.hitObjCount++;
                                manager.Add(action.objectA, objA);
                            }
                        }
                        break;
                    }
                }
            }

            // ====== Debug ��� ======
            counter.Log();
        }

        /// <summary>
        /// ����ѵ���Ĳ��Լƻ�
        /// </summary>
        /// <param name="useFileID"></param>
        public static void RemoveTestPlan(bool useFileID = true)
        {
            // �Ƴ���ʱĿ������
            var tempTargets = GameObject.FindGameObjectsWithTag(Str.Tags.TempTargetTag);
            foreach(var t in tempTargets)
            {
                DestroyImmediate(t);
            }

            // �Ƴ������� FileIdManager
            FileIDContainer manager = FindObjectOfType<FileIDContainer>();
            if(manager != null)
                DestroyImmediate(manager.gameObject);

            TaskList tasklist = GetTaskListFromJson();
            if(tasklist == null) return;

            foreach(var taskUnit in tasklist.taskUnits)
            {
                foreach(var action in taskUnit.actionUnits)
                {
                    if(action.type == "Move") continue;     // �������


                    GameObject objA = FileIDResolver.FindGameObject(action.objectA, useFileID);
                    if(objA == null) continue;

                    if(action.type == "Grab")
                    {
                        XRGrabbable grabbable = objA.GetComponent<XRGrabbable>();
                        if(grabbable != null)
                        {
                            UnityEngine.Object.DestroyImmediate(grabbable, true);
                            Debug.Log($"Removed XRGrabbable from {objA.name}");
                        }
                    }
                    else if(action.type == "Trigger")
                    {
                        XRTriggerable triggerable = objA.GetComponent<XRTriggerable>();
                        if(triggerable != null)
                        {
                            // ����¼��б�
                            triggerable.triggerringEvents.Clear();
                            triggerable.triggerredEvents.Clear();

                            UnityEngine.Object.DestroyImmediate(triggerable, true);
                            Debug.Log($"Removed XRTriggerable from {objA.name}");
                        }
                    }
                    else if(action.type == "Transform")
                    {
                        XRTransformable transformable = objA.GetComponent<XRTransformable>();
                        if(transformable != null)
                        {
                            UnityEngine.Object.DestroyImmediate(transformable, true);
                            Debug.Log($"Removed XRTransformable from {objA.name}");
                        }

                        if(PrefabUtility.IsPartOfPrefabAsset(objA))
                        {
                            EditorUtility.SetDirty(objA);
                            AssetDatabase.SaveAssets();
                        }
                    }

                    if(PrefabUtility.IsPartOfPrefabAsset(objA))
                    {
                        EditorUtility.SetDirty(objA);
                        AssetDatabase.SaveAssets();
                    }
                }
            }
        }

        private List<BaseAction> TaskGenerator(TaskUnit taskUnit)
        {
            if(taskUnit.actionUnits.Count == 0)
            {
                Debug.LogError($"{Str.Tags.LogsTag} {taskUnit} is null");
                return null;
            }

            List<BaseAction> task = new List<BaseAction>();

            for(int actionIndex = 0; actionIndex < taskUnit.actionUnits.Count; actionIndex++)
            {
                var action = taskUnit.actionUnits[actionIndex];
                var debugText = new RichText()
                    .Add($"[Task {_index}][Action {actionIndex}] ", color: Color.yellow)
                    .Add("Type: ", color: Color.yellow)
                    .Add(action.type ?? "Unknown", color: Color.cyan)
                    .Add(" | Source: ", color: Color.white)
                    .Add(action.objectA ?? "null", color: Color.green);

                switch(action)
                {
                    case GrabActionUnit grab:
                    string targetInfo = grab.objectB ?? (grab.targetPosition?.ToString() ?? "null");
                    debugText.Add(" | Target: ", color: Color.white)
                             .Add(targetInfo, color: Color.cyan);
                    break;

                    case TransformActionUnit transform:
                    debugText.Add(" | ��Pos: ", color: Color.white)
                             .Add(transform.deltaPosition.ToString(), color: Color.cyan)
                             .Add(" | ��Rot: ", color: Color.white)
                             .Add(transform.deltaRotation.ToString(), color: Color.cyan)
                             .Add(" | ��Scale: ", color: Color.white)
                             .Add(transform.deltaScale.ToString(), color: Color.cyan);
                    break;

                    case TriggerActionUnit trigger:
                    int triggingCount = trigger.triggerringEvents?.Count ?? 0;
                    int trigredCount = trigger.triggerredEvents?.Count ?? 0;
                    debugText.Add(" | TriggerringEvents: ", color: Color.white)
                             .Add(triggingCount.ToString(), color: Color.magenta)
                             .Add(" | TriggerredEvents: ", color: Color.white)
                             .Add(trigredCount.ToString(), color: Color.magenta);
                    break;

                    case MoveActionUnit move:
                    targetInfo = move.objectB ?? (move.targetPosition?.ToString() ?? "null");
                    debugText.Add(" | Target: ", color: Color.white)
                             .Add(targetInfo, color: Color.cyan);
                    break;

                    case SocketActionUnit socketDbg:
                    debugText.Add(" | Mode: ", color: Color.white)
                             .Add(socketDbg.socketMode ?? "insert", color: Color.magenta);
                    break;
                }
                Debug.Log(debugText);

               


                if(action.type == "Grab")
                {
                    objA = GetOrCreateManager().GetObject(action.objectA);
                    if(objA == null) continue;

                    GrabActionUnit grabAction = action as GrabActionUnit;
                    if(grabAction == null) continue;
                    XRGrabbable grabbable = objA.AddComponent<XRGrabbable>();
                    Debug.Log($"Added XRGrabbable component to {objA.name}");

                    if(grabAction.objectB != null)
                    {
                        objB = GetOrCreateManager().GetObject(grabAction.objectB);
                        grabbable.destination = objB.transform;
                    }
                    else if(grabAction.targetPosition != null)// ʹ�� Vector3��Ϊ target
                    {
                        Vector3 targetPos = (Vector3)grabAction.targetPosition;
                        // �Ȳ��ҳ������Ƿ�������ʱĿ��
                        GameObject targetObj = GameObject.Find($"{objA.name}_TargetPosition");
                        if(targetObj == null)
                        {
                            targetObj = new GameObject($"{objA.name}_TargetPosition_{Str.Tags.TempTargetTag}");
                            targetObj.transform.position = targetPos;
                            targetObj.tag = Str.Tags.TempTargetTag;  // ����ʱĿ��ӱ�ǣ��������ɾ��
                        }
                        else
                        {
                            targetObj.transform.position = targetPos; // ����λ��
                        }

                        grabbable.destination = targetObj.transform;
                        Debug.Log($"Set {objA.name}'s destination to position {targetPos}");
                    }
                    else
                    {
                        Debug.LogError("Lacking of Destination");
                    }
                    task.AddRange(GrabTask(grabbable));
                }
                else if(action.type == "Trigger")
                {
                    objA = GetOrCreateManager().GetObject(action.objectA);
                    if(objA == null) continue;

                    TriggerActionUnit triggerAction = action as TriggerActionUnit;
                    if(triggerAction == null) continue;
                    XRTriggerable triggerable = objA.AddComponent<XRTriggerable>();
                    Debug.Log($"Added XRTriggerable component to {objA.name}");

                    if(triggerAction.trigerringTime != null) triggerable.triggeringTime = (float)triggerAction.trigerringTime;
                    ParameterResolver.BindEventList(triggerAction.triggerringEvents, triggerable.triggerringEvents);
                    ParameterResolver.BindEventList(triggerAction.triggerredEvents, triggerable.triggerredEvents);

                    task.AddRange(TriggerTask(triggerable));
                }
                else if(action.type == "Transform")
                {
                    objA = GetOrCreateManager().GetObject(action.objectA);
                    if(objA == null) continue;

                    TransformActionUnit transformAction = action as TransformActionUnit;
                    if(transformAction == null) continue;
                    XRTransformable transformable = objA.AddComponent<XRTransformable>();
                    Debug.Log($"Added XRTransformable component to {objA.name}");

                    // ���ñ任����
                    if(transformAction.trigerringTime != null) transformable.triggerringTime = (float)transformAction.trigerringTime;
                    transformable.deltaPosition = transformAction.deltaPosition;
                    transformable.deltaRotation = transformAction.deltaRotation;
                    transformable.deltaScale = transformAction.deltaScale;

                    if(transformAction.trigerringTime != null)
                        transformable.triggerringTime = (float)transformAction.trigerringTime;

                    task.AddRange(TransformTask(transformable));
                }
                else if(action.type == "Move")
                {
                    // ˼·��Grab����һ��
                    Vector3 destination = transform.position;
                    MoveActionUnit moveAction = action as MoveActionUnit;
                    if(moveAction == null) continue;

                    if(moveAction.objectB != null)
                    {
                        objB = GetOrCreateManager().GetObject(moveAction.objectB);
                        destination = objB.transform.position;
                    }
                    else if(moveAction.targetPosition != null)// ʹ�� Vector3��Ϊ target
                    {
                        Vector3 targetPos = (Vector3)moveAction.targetPosition;
                        // �Ȳ��ҳ������Ƿ�������ʱĿ��
                        GameObject targetObj = GameObject.Find($"{objB.name}_TargetPosition");
                        if(targetObj == null)
                        {
                            targetObj = new GameObject($"{objB.name}_TargetPosition_{Str.Tags.TempTargetTag}");
                            targetObj.transform.position = targetPos;
                            targetObj.tag = Str.Tags.TempTargetTag;  // ����ʱĿ��ӱ�ǣ��������ɾ��
                        }
                        else
                        {
                            targetObj.transform.position = targetPos; // ����λ��
                        }

                        destination = targetObj.transform.position;
                        Debug.Log($"Set {objB.name}'s destination to position {destination}");
                    }
                    else
                    {
                        Debug.LogError("Lacking of Destination");
                    }
                    task.Add(new MoveAction(_navMeshAgent, moveSpeed, destination));
                }
                else if(action.type == "Socket")
                {
                    objA = GetOrCreateManager().GetObject(action.objectA);
                    if(objA == null) continue;

                    SocketActionUnit socketAction = action as SocketActionUnit;
                    if(socketAction == null) continue;

                    var socket = objA.GetComponent<UnityEngine.XR.Interaction.Toolkit.XRSocketInteractor>();
                    if(socket == null)
                    {
                        Debug.LogError($"No XRSocketInteractor found on {objA.name}");
                        continue;
                    }

                    SocketAction.Mode mode = (socketAction.socketMode == "remove")
                        ? SocketAction.Mode.Remove
                        : SocketAction.Mode.Insert;

                    UnityEngine.XR.Interaction.Toolkit.IXRSelectInteractable interactableObject = null;
                    if(!string.IsNullOrEmpty(socketAction.insertedObjectFileId))
                    {
                        var insertedObj = GetOrCreateManager().GetObject(socketAction.insertedObjectFileId);
                        if(insertedObj != null)
                        {
                            // Prefer XRBaseInteractable (implements IXRSelectInteractable)
                            var xrInteractable = insertedObj.GetComponent<UnityEngine.XR.Interaction.Toolkit.XRBaseInteractable>();
                            if(xrInteractable == null)
                                xrInteractable = insertedObj.GetComponentInParent<UnityEngine.XR.Interaction.Toolkit.XRBaseInteractable>();
                            interactableObject = xrInteractable;
                        }
                        else
                        {
                            Debug.LogWarning($"Socket inserted_object_fileID not found: fileID={socketAction.insertedObjectFileId}");
                        }
                    }

                    task.Add(new SocketAction(socket, mode, interactableObject));
                }
            }
            return task;
        }

        private new void Start()
        {
            base.Start();
            _taskUnits = GetTaskListFromJson().taskUnits;  // ��ʼ��_taskList
        }
    }
}
