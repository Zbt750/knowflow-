import { describe,it,expect,vi,beforeEach } from "vitest";
vi.mock("./client",()=>({api:{get:vi.fn(),post:vi.fn()}}));
import {api} from "./client";
import {sendPracticeRequest,planPracticeRequest,listPracticeRequests,declinePracticeRequest} from "./practiceRequests";
beforeEach(()=>{vi.clearAllMocks();});
describe('Practice Request responsibility boundaries',()=>{
  it('confirmation A only sends request, never calls DailyPlan APIs',async()=>{
    vi.mocked(api.post).mockResolvedValue({status:'pending'});await sendPracticeRequest('r','qa');
    expect(api.post).toHaveBeenCalledWith('/api/practice-requests/r/send',{source_conversation_id:'qa'});
    expect(api.post).toHaveBeenCalledTimes(1);
  });
  it('Planner handling has distinct study identity and is not confirmation B',async()=>{
    vi.mocked(api.post).mockResolvedValue({request:{status:'proposed'},task:{}});await planPracticeRequest('r','study');
    expect(api.post).toHaveBeenCalledWith('/api/practice-requests/r/plan',{study_session_id:'study'});
  });
  it('polling is GET only; declining has its own endpoint',async()=>{
    vi.mocked(api.get).mockResolvedValue([]);await listPracticeRequests();expect(api.post).not.toHaveBeenCalled();
    vi.mocked(api.post).mockResolvedValue({status:'declined'});await declinePracticeRequest('r');
    expect(api.post).toHaveBeenCalledWith('/api/practice-requests/r/decline',{});
  });
});
