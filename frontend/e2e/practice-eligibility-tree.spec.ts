import { expect, test } from "@playwright/test";

// Browser contract test, not a real inventory/model evaluation.
test("原卷标记节点有可练Question时可选，仅引用与未合格题不冒充练习", async ({ page }) => {
  const eligible = { id:"eligible",code:"math.eligible",name:"伴随矩阵与可逆矩阵",is_assessable:true,is_reference_only:true,practice_eligible_question_count:2,online_question_count:3,children:[] };
  await page.route("**/api/**", async route => {
    const path=new URL(route.request().url()).pathname;
    if(path==="/api/health")return route.fulfill({json:{status:"ok",database:"connected"}});
    if(path==="/api/plans/today")return route.fulfill({json:{status:"active",plan_id:"plan",study_date:"2026-10-07",items:[],total_count:0,completed_count:0,summary_kps:[],type_summary:{},estimated_minutes:0,remaining_minutes:0}});
    if(path==="/api/knowledge/tree")return route.fulfill({json:{nodes:[{id:"root",code:"math",name:"数学",is_assessable:false,children:[eligible,
      {id:"references",code:"math.references",name:"只有原卷引用",is_assessable:true,is_reference_only:true,practice_eligible_question_count:0,online_question_count:0,children:[]},
      {id:"blocked",code:"math.blocked",name:"题目未达练习资格",is_assessable:true,practice_eligible_question_count:0,online_question_count:4,children:[]},
    ]}]}});
    if(path==="/api/knowledge/eligible")return route.fulfill({json:{questions:[
      {id:"q1",stem:"合法选择题一",is_variant:false,trust:{practice_eligible:true}},
      {id:"q2",stem:"合法选择题二",is_variant:false,trust:{practice_eligible:true}},
      {id:"q3",stem:"未达资格的题目",is_variant:false,trust:{practice_eligible:false}},
    ]}});
    if(path==="/api/practice-requests")return route.fulfill({json:[]});
    return route.fulfill({json:[]});
  });
  await page.goto("/study");
  await page.getByRole("button",{name:"追加练习题",exact:true}).click();
  await page.getByTestId("question-picker-search").fill("伴随矩阵");
  const node=page.getByTestId("question-picker-node-math.eligible");
  await expect(node).toBeVisible();await node.click();
  const picker=page.getByTestId("question-picker");
  await expect(picker.getByRole("checkbox")).toHaveCount(2);
  await picker.getByRole("checkbox").first().check();
  await expect(page.getByTestId("confirm-append")).toContainText("确认追加（1）");
  await page.getByTestId("question-picker-search").fill("");
  await expect(page.getByTestId("question-picker-node-math.references")).toHaveCount(0);
  await expect(page.getByTestId("question-picker-node-math.blocked")).toHaveCount(0);
});
