// Existing UI fixtures must never synchronize synthetic records into a live DB.
module.exports = async function isolatePersonalState(context) {
  let snapshot = {revision:0, data:{}, updated_at:''};
  await context.route(/\/api\/intern-summary(?:\/[^?]*)?(?:\?.*)?$/, route =>
    route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({enabled:false,logs_count:0,summaries:[]})}));
  await context.route('**/api/tasks', route => route.fulfill({status:200,contentType:'application/json',body:'{"tasks":[]}'}));
  await context.route(/\/api\/personal-state(?:\/[^?]*)?(?:\?.*)?$/, route => {
    const pathname = new URL(route.request().url()).pathname;
    const send = (body, status=200) => route.fulfill({status, contentType:'application/json', body:JSON.stringify(body)});
    if (pathname.endsWith('/save')) {
      const body = route.request().postDataJSON();
      if (body.base_revision !== snapshot.revision) return send({error:'测试版本冲突',snapshot},409);
      snapshot = {revision:snapshot.revision+1,data:body.data,updated_at:new Date().toISOString()};
      return send(snapshot);
    }
    if (pathname === '/api/personal-state') return send(snapshot);
    return send({error:'此测试不支持这个资料操作'},400);
  });
};
